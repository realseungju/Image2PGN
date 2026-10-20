# Selected historical games

The catalog contains 12 selected games / 744 recorded plies. Only game-score
facts and main-line moves are included; source commentary and analysis branches
are not redistributed. No missing historical rating is inferred.

| ID | White — Black | Source year | Plies |
|---|---|---|---|
| fischer-benko-1963 | Fischer — Benko | 1963 | 41 |
| byrne-fischer-1956 | Donald Byrne — Fischer | 1956 | 82 |
| anderssen-kieseritzky-1851 | Anderssen — Kieseritzky | 1851 | 45 |
| anderssen-dufresne-1852 | Anderssen — Dufresne | 1852 | 47 |
| morphy-opera-1858 | Morphy — Duke Karl / Count Isouard | 1858 | 33 |
| levitsky-marshall-1912 | Levitsky — Marshall | 1912 | 46 |
| capablanca-marshall-1918 | Capablanca — Marshall | 1918 | 71 |
| rotlewi-rubinstein-1907 | Rotlewi — Rubinstein | 1907 | 50 |
| botvinnik-capablanca-1938 | Botvinnik — Capablanca | 1938 | 81 |
| kasparov-topalov-1999 | Kasparov — Topalov | 1999 | 87 |
| karpov-kasparov-1985-g16 | Karpov — Kasparov | 1985 | 80 |
| fischer-spassky-1972-g6 | Fischer — Spassky | 1972 | 81 |

## Provenance

Each JSON item retains source URLs, retrieval date, the downloaded PGN Mentor
archive's SHA-256, the decompressed PGN file's SHA-256, the selected game headers,
ply count, and a SHA-256 of ASCII UCI moves joined by single spaces. These record
the source edition used; legal replay alone does not prove historical accuracy.
The original two scores were independently matched against the Fischer archive.

PGN Mentor makes its player files freely available at
https://www.pgnmentor.com/files.html. Source links on each card point to the
particular player archive. The original two entries also retain their earlier
FIDE/Lichess/chess-association references.

## Edition limits

- The Immortal Game is the commonly transmitted 23.Be7# score. Its actual ending
  is historically disputed; the UI explicitly identifies this as a source edition.
- Unknown month/day values remain `??`. Source event names are retained, including
  abbreviations. A source label is not an independent historical verification.
- Rubinstein's game ends at 25...Rh3 and Fischer–Benko ends at 21.Ne2. Neither has
  a made-up checkmate continuation appended to the played score.
- The Opera Game qualifies as a named historical classic despite missing Elo and
  its consultation opponents; online results still require both ratings >=2400.
- These games cover selected examples, not the universe of famous games. Finding
  the same position supplies candidates, not proof of a screenshot's origin.

To add a game, select a specific source score, retain its provenance, strip
annotations/variations, check every move and terminal result, then run
`python -m pytest tests/test_famous_catalog.py tests/test_master_games.py -q`.
