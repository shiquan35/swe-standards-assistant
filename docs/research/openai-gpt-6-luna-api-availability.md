# Official OpenAI documentation check: `gpt-6-luna`

Checked 2026-11-11 against OpenAI first-party API documentation only.

## Findings

- **Exact identifier exists:** OpenAI's model catalog has a GPT-6 Luna page that names its Model ID as `gpt-6-luna` and its default snapshot as `gpt-6-luna`.
- **API availability is documented:** The model page explicitly marks the `v1/responses` endpoint as supported. The Responses API reference's model identifier enum also includes `gpt-6-luna`. This establishes published API support; account/project access may still depend on OpenAI's availability and access controls.
- **Structured Outputs is documented as supported:** The model page lists `structured_outputs` under Supported features. The Responses API reference documents JSON Schema output using `text.format` with `type: "json_schema"`.

This finding concerns the API identifier in OpenAI's documentation only. It does not derive that identifier from, or equate it with, any assistant/model self-description.

## Primary sources

1. OpenAI, [GPT-6 Luna model page](https://developers.openai.com/api/docs/models/gpt-6-luna) — exact model ID, default snapshot, endpoint support table, and supported-features list.
2. OpenAI, [Models catalog](https://developers.openai.com/api/docs/models) — lists GPT-6 Luna as a model and describes latest models as available via the Responses API.
3. OpenAI, [Responses API reference](https://developers.openai.com/api/reference/resources/responses) — includes `gpt-6-luna` in the Responses model identifiers and specifies the `json_schema` output format.
4. OpenAI, [Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs) — documents Structured Outputs with `json_schema` through the Responses API and supported-model guidance.
5. OpenAI, [List models API reference](https://developers.openai.com/api/reference/resources/models/methods/list) — documents `GET /v1/models` as listing currently available models and explains that returned model IDs can be referenced in API endpoints. The live result is organization/account-dependent and was not queried because no API credentials were provided.
