# PDF Ingest Provider Limits

Date: 2026-07-01

This note records the current provider constraints behind GEODE's
`document_ingest` page-range policy.

## Summary

GEODE accepts a wide `page_range` such as `1-460`. The range is a user intent,
not a promise that any single provider request can handle the whole span.
`document_ingest` applies provider-specific execution limits underneath the
same manifest/page bundle.

## OpenAI

Source: https://developers.openai.com/api/docs/guides/file-inputs

Observed constraints:

- Responses API accepts files as `input_file` by file ID, base64 file data, or
  external URL.
- PDF parsing places extracted text and page images into context, so large PDFs
  can become expensive or hit context limits before the user expects it.
- Each file must be under 50 MB, and the combined file-input request limit is
  50 MB.
- PDF parsing with text plus page images requires a vision-capable model.

GEODE policy:

- Keep `page_range` wide at the tool boundary.
- Preflight the effective PDF file size against 50 MB.
- When `page_range` is provided, slice the local PDF before sending it to
  OpenAI, because OpenAI file input is file-oriented rather than page-oriented.
- Do not impose a small page cap in GEODE; let model context and file-size
  limits be the deciding constraints.

## Claude

Sources:

- https://docs.anthropic.com/en/docs/build-with-claude/pdf-support
- https://docs.anthropic.com/en/docs/build-with-claude/context-windows
- https://docs.anthropic.com/en/api/errors

Observed constraints:

- Messages API request size limit is 32 MB.
- PDF support is available for active models.
- 1M-token context models can include up to 600 images or PDF pages per request.
- 200k-token context models can include up to 100 images or PDF pages per
  request.
- Dense PDFs can fill context before reaching page limits.

GEODE policy:

- Treat Claude page limits as model-family policy: 600 pages for known 1M
  Claude models, 100 pages for older or unknown Claude models.
- When `page_range` is provided and exceeds the model limit, split it into
  Claude-sized local PDF slices and merge outputs into one GEODE document
  bundle.
- When no `page_range` is provided and `pdfinfo` shows too many pages, return a
  validation error asking for `page_range` instead of sending a request that is
  likely to fail.
- Use a conservative base64 payload preflight for the 32 MB Messages limit.

## Zhipu / Z.AI GLM-OCR

Sources:

- https://docs.z.ai/api-reference/tools/layout-parsing
- https://docs.z.ai/guides/vlm/glm-ocr
- https://docs.bigmodel.cn/api-reference/模型-api/文档解析

Observed constraints:

- `layout_parsing` accepts `model=glm-ocr` and a PDF/JPG/PNG `file` as URL or
  base64 data URI.
- The API exposes `start_page_id` and `end_page_id` for PDF page selection.
- GLM-OCR guide and the Chinese API reference list PDF <= 50 MB and maximum
  support of 100 pages.
- The English API reference currently says maximum support is 30 pages. This
  conflicts with the guide/API reference in Chinese.
- Responses include `md_results`, `layout_details`, `data_info`, `usage`, and
  `request_id`.

GEODE policy:

- Do not slice PDFs locally for Zhipu. Use `start_page_id` and `end_page_id`.
- Default optimistically to 100-page request chunks because the model guide and
  Chinese API reference agree on 100 pages, but treat this as a compatibility
  policy rather than a settled endpoint limit.
- If a 100-page chunk fails, retry that chunk as 30-page chunks to match the
  stricter English API reference.
- Preflight the source PDF against 50 MB.

## Unlimited-OCR Lesson

Source: https://arxiv.org/abs/2606.23050

Unlimited-OCR's practical lesson for GEODE is continuity: user-facing document
selection should stay document-shaped, while backend chunks remain execution
details. GEODE should avoid forcing users to reason in provider page caps.

The current implementation keeps the `document_ingest` output as one bundle even
when provider calls are split. Future local backends can add `docling`,
`MinerU`, `PaddleOCR`, `olmOCR`, or `Unlimited-OCR` as optional extractors
without changing this user-facing contract.
