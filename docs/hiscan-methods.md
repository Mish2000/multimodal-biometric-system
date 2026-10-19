# The research methods on HiScan PRO captures (H10)

## Setup

The three fingerprint methods of the research ran unchanged on 2026-10-19 from
the pinned research commit `606c8d3` (`methods/research-pin.toml`), each in its
own research environment, through `methods/hiscan_eval.py` (291 s in all):

| Method | Environment | Score |
| --- | --- | --- |
| OpenCV SIFT | project: OpenCV 4.13.0, one thread | RANSAC homography inliers |
| Pore SIFT | Pore SIFT: Python 3.10, OpenCV 3.4.18, PyTorch 1.13 CPU, one thread | mutual best matches of SIFT descriptors at detected pores (`basic`) |
| Learned pore descriptor, second training | GPU: PyTorch 2.13, RTX 5080 Laptop | the same `basic` count on learned descriptors at the same pores |

Images: the second set (`live002`, H9: three placements of each of the ten
fingers through the OEM route) and the researcher's first set (one capture
per finger, saved on 2026-09-09 with the vendor control panel's "Save 1000
DPI"). Pairs:

- **A**: placements of the second set against each other, the earlier
  capture as reference: 30 same-finger and 405 different-finger pairs.
- **B**: the first set as reference against the second set: 30 same-finger
  and 270 different-finger pairs.

Every pair is counted at the operational thresholds at FAR 0.1 % of the
research's plain vs plain scenarios (development pairs, R7): accepted when
the score is above OpenCV SIFT 57 (RxJ) / 58 (QxJ), Pore SIFT 21 / 21, and the
learned descriptor 13 / 14. A failed comparison scores 0. Fusions were not
evaluated. Scores, features and timings are in the ignored
`captures/live002/evaluation/`; this page holds aggregate numbers only.

## Accepted pairs

A, placements of the second set (30 same-finger, 405 different-finger pairs):

| Method | Same finger accepted (RxJ / QxJ) | Different fingers accepted | Same-finger scores, min / median | Different-finger scores, median / max |
| --- | --- | --- | --- | --- |
| OpenCV SIFT | 28 / 28 | 0 / 0 | 14 / 383.5 | 6 / 17 |
| Pore SIFT | 23 / 23 | 71 / 71 | 10 / 36 | 15 / 37 |
| Learned pore descriptor | 26 / 25 | 28 / 19 | 4 / 91.5 | 7 / 21 |

B, first set against second set (30 same-finger, 270 different-finger pairs):

| Method | Same finger accepted (RxJ / QxJ) | Different fingers accepted | Same-finger scores, min / median | Different-finger scores, median / max |
| --- | --- | --- | --- | --- |
| OpenCV SIFT | 1 / 1 | 0 / 0 | 5 / 11.5 | 6 / 31 |
| Pore SIFT | 18 / 18 | 62 / 62 | 9 / 23.5 | 16 / 33 |
| Learned pore descriptor | 20 / 18 | 17 / 7 | 2 / 16 | 8 / 20 |

For description only, the lowest threshold that accepts none of these
different-finger pairs would accept, in A, OpenCV SIFT 28 of 30 same-finger
pairs (above 17), the learned descriptor 24 (above 21) and Pore SIFT 13 (above
37); in B, 3, 11 and 1. Such thresholds rest on one person's 405 or 270 pairs
and set no FAR.

## Observations

- OpenCV SIFT separates the placements of one session: its two misses in A
  are the third left-ring placement against the first two (14 and 17), the
  placements that overlap least (H9). Against the first set its same-finger
  scores are low (median 11.5): capture route, gray levels, finger area and
  six weeks all differ.
- At the SD302 thresholds the two pore methods accept many different-finger
  pairs. Their score counts mutual best descriptor matches without a
  geometric check, and these captures have more detected pores (median 1,602
  per image, 1,151–2,720; thumbs 1,920–2,720) than SD302 plain images, where
  the same detector found a median of 924 (J), 1,262 (Q) and 1,351 (R) per
  image in the research run's features. Different-finger pairs with more
  pores score higher (A: the third of the pairs with the fewest pores has a
  median of 14 for Pore SIFT and 5 for the learned descriptor, the third with
  the most 17 and 9), and all nine pairs of the two thumbs pass Pore SIFT's
  threshold. Same-hand pairs are not over-represented among the accepted ones
  (Pore SIFT 46 %, learned 43 %, against 44 % of all different-finger pairs).
- Not yet separated as causes: the number of pores per capture, same-device
  pairs (the SD302 thresholds come from cross-device pairs, Crossmatch against
  Morpho), one person's fingers, and the gray levels of the OEM route (see
  `docs/scanner-native-capture.md`).
- Pores: the second set has a median of 1,602 per image, the first set 1,546
  (1,314–1,880).

## Time and template size

Medians on the second-set images; extraction is what a new capture costs, and
one 1:1 attempt is one extraction plus one comparison.

| Method | Extraction | Comparison | One 1:1 attempt | Template |
| --- | --- | --- | --- | --- |
| OpenCV SIFT | 0.25 s | 147 ms | 0.40 s | 4.1 MiB |
| Pore SIFT | 3.12 s, of which pore detection 3.09 s | 32 ms | 3.15 s | 814 KiB |
| Learned pore descriptor | 3.18 s: the same pore detection, 0.08 s description on the GPU | 0.5 ms | 3.18 s | 400 KiB |

Pore detection ran on one CPU thread, as in the research's timings.

## Limits

- One person: the different-finger pairs are the researcher's other fingers,
  not other people. Even no accepted pair out of 405 would bound FAR only
  below about 0.74 % (95 %); thresholds for the HiScan PRO need other people.
- The pairs come from one session (A) and from two capture routes six weeks
  apart (B); the system will enrol and verify through the OEM route.
