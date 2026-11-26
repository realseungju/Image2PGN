"""Full-grid evidence and main-board selection for the opt-in grid-v2 path."""
from dataclasses import asdict
import cv2
import numpy as np
from .board_candidates import (BoardCandidate, find_board_candidates, find_corner_alternatives, find_corner_candidates,
                               bounds_iou, _refine, _distinct)

MIN_BAND_CONTRAST = .20


def grid_evidence(image, bounds):
    """Measure parity agreement, weakest outside row/column and seven-line spacing.

    Medians of four corner patches reduce central-piece interference. Thresholds
    are development heuristics, not calibrated probabilities or proof of a board.
    """
    x,y,w,h = bounds
    crop = cv2.resize(image[y:y+h,x:x+w], (256,256), interpolation=cv2.INTER_AREA)
    lab = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB).astype(np.float32)
    colors=[]
    for row in range(8):
        for col in range(8):
            tile=lab[row*32:(row+1)*32,col*32:(col+1)*32]
            samples=np.concatenate([tile[y:y+5,x:x+5].reshape(-1,3) for y in (3,24) for x in (3,24)])
            colors.append(np.median(samples,axis=0))
    colors=np.array(colors).reshape(8,8,3)
    parity=np.indices((8,8)).sum(axis=0)%2
    centers=np.array([np.median(colors[parity==i],axis=0) for i in (0,1)])
    contrast=float(np.linalg.norm(centers[0]-centers[1]))
    projection = (colors @ (centers[0] - centers[1])) / max(contrast * contrast, 1.)
    band_contrasts = [
        np.median(band[pattern == 0]) - np.median(band[pattern == 1])
        for values, patterns in ((projection, parity), (projection.T, parity.T))
        for band, pattern in zip(values, patterns)
    ]
    distances=np.linalg.norm(colors[:,:,None,:]-centers[None,None,:,:],axis=3)
    agreement=(distances.argmin(axis=2)==parity)
    parity_score=float(agreement.mean()) if contrast >= 6 else 0.0
    outer=float(min(agreement[0].mean(),agreement[-1].mean(),agreement[:,0].mean(),agreement[:,-1].mean())) if contrast >= 6 else 0.0
    # Long color changes accumulated across rows/columns, near the seven grid lines.
    gray=cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY).astype(np.float32)
    line_scores=[]
    for axis in (0,1):
        response=np.mean(np.abs(np.diff(gray,axis=axis)),axis=1-axis)
        background=max(float(np.median(response)),1.0)
        line_scores.extend(float(response[k-3:k+3].max()) > background*1.5 for k in range(32,256,32))
    lines=float(np.mean(line_scores))
    valid=parity_score>=.78 and outer>=.625 and lines>=.5
    return {'parity':parity_score,'outer':outer,'lines':lines,'contrast':contrast,'valid':bool(valid),
            'weakest_band':float(min(band_contrasts))}


def _search_candidates(image, *, max_search_width=None):
    """Validate cheap coarse proposals before refining expensive local matches.

    A coarse full-grid pass normally identifies the one useful proposal.  If it
    identifies none, refine every proposal as before so borderline grids keep the
    original recovery path.
    """
    coarse=find_board_candidates(image,max_candidates=5,max_search_width=max_search_width,search_step=8,refine=False)
    coarse_scored=[dict(asdict(c),evidence=grid_evidence(image,c.bounds)) for c in coarse]
    promising=[c for c in coarse_scored if c['score']>=.30 and c['evidence']['valid']]
    if promising:
        return coarse_scored
    to_refine=coarse_scored
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    refined=[_refine(gray,BoardCandidate(tuple(c['bounds']),c['score'])) for c in to_refine]
    refined=_distinct(refined,5)
    refined_scored=[dict(asdict(c),evidence=grid_evidence(image,c.bounds)) for c in refined]
    return refined_scored


def _complete(evidence):
    return evidence['valid'] and evidence['weakest_band'] >= MIN_BAND_CONTRAST


def _has_piece_evidence(image, bounds):
    from .board import background_empty_squares, split_squares

    x, y, width, height = bounds
    board = cv2.resize(image[y:y+height, x:x+width], (640, 640), interpolation=cv2.INTER_AREA)
    return not all(all(row) for row in background_empty_squares(split_squares(board)))


def _finish_selection(image, chosen, scored, alternatives, *, expanded, reason, ambiguous=False):
    bounds = chosen['bounds']
    selected_evidence = chosen['evidence']
    complete = _complete(selected_evidence)
    ambiguous = ambiguous or not complete
    options = []
    if not complete:
        reason = reason if reason == 'existing_grid_occluded_edge' else 'incomplete_grid'
    elif not _has_piece_evidence(image, bounds):
        recovered = []
        for candidate in find_corner_alternatives(image, bounds):
            candidate_evidence = grid_evidence(image, candidate.bounds)
            if _complete(candidate_evidence) and _has_piece_evidence(image, candidate.bounds):
                recovered.append(dict(asdict(candidate), evidence=candidate_evidence))
        if recovered:
            best = recovered[0]
            bounds, selected_evidence = best['bounds'], best['evidence']
            options.append(list(bounds))
            alternatives = [*recovered[1:], *alternatives]
            reason = 'recovered_populated_board'
        else:
            reason = 'empty_grid'
        scored = [*scored, *recovered]
        ambiguous = True
    elif ambiguous:
        options.append(list(bounds))

    if ambiguous:
        for other in alternatives:
            candidate = other['bounds']
            if (_complete(other['evidence']) and all(bounds_iou(candidate, option) < .5 for option in options)
                    and _has_piece_evidence(image, candidate)):
                options.append(list(candidate))
            if len(options) == 5:
                break
    return tuple(bounds), {
        'candidates': scored, 'expanded_search': expanded, 'requires_review': bool(ambiguous),
        'selected_evidence': selected_evidence, 'selection_reason': reason,
        'review_options': options, 'boundary_action': ('choose_board' if options else 'recapture') if ambiguous else None,
    }


def select_board(image):
    """Return original-coordinate bounds plus auditable selection/review metadata.

    Established grid geometry is preferred when validated. Repeated board patterns
    can otherwise create shifted candidates even when their parity looks strong.
    """
    # Preserve a stable legacy crop when independent full-grid evidence agrees.
    # One occluded border may still carry strong global evidence; flag it for review.
    from .board import find_screenshot_board
    existing = find_screenshot_board(image)
    if existing is not None:
        evidence = grid_evidence(image, existing)
        occluded = evidence['parity'] >= .90 and evidence['lines'] >= .85 and evidence['outer'] >= .5
        if evidence['valid'] or occluded:
            candidate = {'bounds':list(existing),'score':None,'source':'existing_grid','evidence':evidence}
            return _finish_selection(image, candidate, [candidate], [], expanded=False,
                                     reason='existing_grid_validated' if evidence['valid'] else 'existing_grid_occluded_edge')
    # The common path searches at most 640px, refining only five diverse proposals.
    scored=_search_candidates(image,max_search_width=640)
    valid=[c for c in scored if c['score']>=.30 and c['evidence']['valid']]
    expanded=False
    if not valid:
        expanded=True
        scored=_search_candidates(image)
        valid=[c for c in scored if c['score']>=.30 and c['evidence']['valid']]
    if not valid:
        # Piece-tolerant fallback: only complete grids found by tile-corner matching.
        corner=[dict(asdict(c),evidence=grid_evidence(image,c.bounds)) for c in find_corner_candidates(image)]
        scored=[*scored,*corner]
        complete=[c for c in corner if _complete(c['evidence'])]
        if complete:
            complete.sort(key=lambda c:(c['bounds'][2]*c['bounds'][3],c['score']),reverse=True)
            ambiguous=any(bounds_iou(complete[0]['bounds'],c['bounds'])<.5
                          and c['bounds'][2]*c['bounds'][3]>=.6*complete[0]['bounds'][2]*complete[0]['bounds'][3]
                          for c in complete[1:])
            return _finish_selection(image, complete[0], scored, complete[1:], expanded=expanded, ambiguous=ambiguous,
                                     reason='ambiguous_main_board' if ambiguous else 'corner_weighted_full_grid')
    if not valid:
        return None, {'candidates':scored,'expanded_search':expanded,'requires_review':True,
                      'selection_reason':'no_valid_full_grid','review_options':[],'boundary_action':'recapture'}
    # Area is a prior only after all candidates have passed full-grid evidence.
    valid.sort(key=lambda c:(c['bounds'][2]*c['bounds'][3],c['score']),reverse=True)
    chosen=valid[0]
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    refined=_refine(gray, BoardCandidate(tuple(chosen['bounds']),chosen['score']),resolution=320,padding=.06,step=2)
    refined_evidence=grid_evidence(image,refined.bounds)
    if refined_evidence['valid']:
        chosen=dict(asdict(refined),evidence=refined_evidence)
        # Weak-color themes have a flatter downscaled correlation surface. Pay
        # for the established 640px polish only there; strong-color boards use a
        # narrow 320px pass after the wider coarse correction.
        if refined_evidence['contrast'] < 50:
            precise=_refine(gray,refined,resolution=640,padding=.015,step=1)
            precise_evidence=grid_evidence(image,precise.bounds)
            if precise_evidence['valid']:
                chosen=dict(asdict(precise),evidence=precise_evidence)
        else:
            polished=_refine(gray,refined,resolution=320,padding=.01,step=1)
            polished_evidence=grid_evidence(image,polished.bounds)
            if polished_evidence['valid']:
                chosen=dict(asdict(polished),evidence=polished_evidence)
    ambiguous=any(_complete(c['evidence']) and bounds_iou(chosen['bounds'],c['bounds'])<.5
                  and c['bounds'][2]*c['bounds'][3]>=.6*chosen['bounds'][2]*chosen['bounds'][3] for c in valid[1:])
    return _finish_selection(image, chosen, scored, valid[1:], expanded=expanded, ambiguous=ambiguous,
                             reason='ambiguous_main_board' if ambiguous else 'largest_valid_full_grid')
