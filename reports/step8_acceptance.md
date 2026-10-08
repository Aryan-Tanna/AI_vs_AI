# Step 8 acceptance: THEMIS-LOCAL layer 2

```json
{
  "case_id": "DEV_0001",
  "precedent_used": "2020_NCLAT_DEL_748#3351031e441f",
  "honest_first_attempt_pass_rate": 1.0,
  "honest": 6,
  "mutations_caught": "3/3"
}
```

| argument | kind | expected | hard errors | warnings | as expected |
| --- | --- | --- | --- | --- | --- |
| PETITIONER ground 1 | HONEST | - | - | - | yes |
| PETITIONER ground 2 | HONEST | - | - | - | yes |
| PETITIONER ground 3 | HONEST | - | - | - | yes |
| RESPONDENT ground 1 | HONEST | - | - | - | yes |
| fabricated exhibit content | MUTATED | ERR_EXHIBIT_CONTENT_FABRICATED | ERR_EXHIBIT_CONTENT_FABRICATED | - | yes |
| record item that does not exist | MUTATED | ERR_FACT_NOT_IN_RECORD | ERR_FACT_NOT_IN_RECORD | - | yes |
| honest citation (the precedent's own rule) | HONEST | - | - | WARN_PREREQUISITE_UNADDRESSED | yes |
| inverted holding | MUTATED | ERR_PRECEDENT_MISATTRIBUTED | ERR_PRECEDENT_MISATTRIBUTED | WARN_PREREQUISITE_UNADDRESSED | yes |
| unverifiable citation | HONEST | - | - | WARN_UNVERIFIABLE_CITATION | yes |
