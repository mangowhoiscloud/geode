# Paper reviews

## JEVDB

[Read the paper review](https://mangowhoiscloud.github.io/geode/research/jevdb/) ·
[Watch the paper review video](https://youtu.be/KKiEyGjGUIo) ·
[Download the review slides (PPTX)](jevdb-seminar-v25.pptx)

Jihwan Ryu's review of **Prune First, Decide Fast: Scalable Semantic Query
Processing with JEVDB**, by Zhengle Wang, Hanxu Yan, Fuheng Zhao, and Chunwei
Liu ([arXiv:2610.02046v1](https://arxiv.org/abs/2610.02046v1)).

The slides explain typed decisions, candidate pruning, reuse, and LLM
escalation, then examine the conditions and limits of the reported benchmarks.
The closing research perspective separates GEODE's personal verifier
experiments from the paper's results. This is a paper review, not a JEVDB
benchmark reproduction.

- Revision: v25, completed October 11, 2026.
- Format: 19 English slides with Korean speaker notes.
- SHA-256: `83d9b2ca13bc7af604927b885b0cce3ba6a43ca96e86b657f4771ae69ac51d8c`.
- The production PPTX, delivered copy, and final submission working copy have
  identical bytes. All 19 speaker-note bodies match the production QA hashes.
- Original paper figures retain their slide-level attribution and CC BY 4.0
  notices. Presenter examples and personal experiments are identified separately.

Only the reviewed PPTX is exported to the website. The build copies this file
to `/geode/research/jevdb-seminar-v25.pptx`; internal review records and other
submission materials are not included. The source file remains unchanged.

### v25 web reader

The JEVDB review uses the Decision Offloading reader's light workspace, scene
list, canvas navigation, and source sheet. The 19 English slide images under
`site/public/research/jevdb-slides-v25/` are unchanged existing v25 PDF review
rasters, extracted from the completed slide-and-script preview. No PDF, slide,
or video was rerendered for this presentation change. The public manifest
records each image digest, the preview HTML/PDF identities, and the unchanged
canonical PPTX digest. The images were also compared byte-for-byte with the
reviewed PDF page rasters. The earlier PDF rendering receipt identifies a
pre-final-note PPTX hash; it is not relabeled as a render of the final PPTX bytes.

`site/src/data/geode/jevdb-slides.json` contains original English slide text
extracted from the published PPTX slide XML, plus bilingual reading notes and
source/condition captions. No speaker notes or private production discussion
are copied into the web reader. Language selection changes navigation and
reading notes, not the original slide art. Each image represents one settled
build; there are no invented intermediate builds or motion controls. Scene 18
retains the separate U8c agent-loop comparison and its limits, distinct from
JEVDB paper results, U3 single judgments, and U8n post-hoc analysis.
