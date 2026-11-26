# Piece-set reference descriptors

`references.npz` holds averaged 32×32 square descriptors (HOG gradients plus
16×16 shape and shading maps) for 11 Lichess piece sets on four Lichess board
themes (blue, brown, green, purple). They were computed from 400 screenshots of
79 public Lichess games captured on 2026-11-25. The screenshots themselves are
not distributed. `infra/build_piece_set_references.py` documents the build;
`references.json` records the cutoffs and the file hash.

The descriptors are low-resolution derivatives of the artwork below. The file as
a whole is distributed under **AGPL-3.0-or-later**
(<https://www.gnu.org/licenses/agpl-3.0.html>), which is compatible with every
source license listed. The MIT license of the ChessLens code does not apply to it.

| Piece set | Author (as credited by Lichess) | License |
|---|---|---|
| cburnett | Colin M.L. Burnett | GPLv2+ |
| celtic | Maurizio Monge | MIT |
| chessnut | Alexis Luengas | Apache 2.0 |
| fantasy | Maurizio Monge | MIT |
| firi | James Faure | CC BY 4.0 |
| merida | Armando Hernandez Marroquin | GPLv2+ |
| mpchess | Maxime Chupin | GPLv3+ |
| pirouetti | pirouetti | AGPLv3+ |
| pixel | therealqtpi | AGPLv3+ |
| rhosgfx | RhosGFX | CC0 1.0 |
| spatial | Maurizio Monge | MIT |

Board images: the lila authors and pirouetti, AGPLv3+. Source of the credits:
<https://github.com/lichess-org/lila/blob/master/COPYING.md> (checked 2026-11-26).

The Lichess `alpha` set ("free for personal non commercial use") was excluded
from the references on purpose. Screens drawn with it fall back to the CNN.
