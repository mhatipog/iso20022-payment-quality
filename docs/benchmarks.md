# Reproducible Spark reconciliation benchmarks

These are **synthetic, correctness-checked** measurements of the canonical
Spark reconciliation stage, **not** banking production throughput or SEPA
conformance tests. The test scripts and raw GitHub Actions logs are public.

## Environment and reproducibility

- Two independent successful GitHub-hosted `ubuntu-latest` workflow runs,
  27 October 2026.
- Python 3.11, Java 17, Spark **4.2.0**, `local[2]` (two Spark worker threads),
  eight Spark shuffle partitions and AQE enabled.
- Sources are generated using Spark `range()`, not transferred from the Python
  driver. Each run includes one Spark groupBy to materialize and count the
  reconciliation outcomes. All counts are asserted against deterministic
  expected values.
- No real customer records, payment instructions or PII are used.
- Reproduce by running the manual
  [Synthetic Spark scale benchmark](../.github/workflows/benchmark-scale.yml)
  workflow or executing the scripts below with a compatible Spark setup.

## Measurements

| Scenario | Rows | Run A (seconds) | Run B (seconds) | Guaranteed accuracy of expected counts |
|---|---:|---:|---:|---|
| Clean, strict physical ID checks | 20,000 | 8.304 | 6.432 | Yes |
| Clean, strict physical ID checks | 100,000 | 4.771 | 3.397 | Yes |
| Clean, upstream-validated unique IDs (checks disabled) | 100,000 | 3.489 | 2.645 | Yes |
| Clean, strict physical ID checks | 1,000,000 | 20.642 | 14.757 | Yes |
| Reused reference + bank exceptions, strict ID checks | 100,000 | — | 3.048 | Yes |
| Reused reference + bank exceptions, strict ID checks | 1,000,000 | — | 14.395 | Yes |

The **clean** 1M case classified 980,000 as `MATCHED`,
10,000 as `AMOUNT_MISMATCH`, and 10,000 as `NO_BOOKING_FOUND`.

The **adversarial** 1M case included a deliberately hot reference shared by
5% of payments, missing bank-entry IDs, inaccurate amounts, reversals,
return codes and pending statements. Its exact classifications were:

| Status | Count |
|---|---:|
| MATCHED | 904,671 |
| AMBIGUOUS_MATCH | 50,000 |
| AMOUNT_MISMATCH | 9,901 |
| INVALID_ENTRY_ID | 9,405 |
| REVERSAL_REQUIRES_REVIEW | 9,035 |
| RETURN_REQUIRES_REVIEW | 8,613 |
| NOT_BOOKED | 8,375 |

Every observed count matched the independently coded oracle.

Raw logs and commit provenance:
- [Clean benchmark run A](https://github.com/mhatipog/iso20022-payment-quality/actions/runs/40528001925)
- [Clean plus adversarial benchmark run B](https://github.com/mhatipog/iso20022-payment-quality/actions/runs/40528602545)
- [Python and Spark functional CI](https://github.com/mhatipog/iso20022-payment-quality/actions/runs/40528602239)

## Important interpretation limits

- **Warm-up, adaptive query planning and runner noise matter.**
  Measurements from later cases in each run benefit from a warm JVM;
  the difference between strict and relaxed checks does *not* establish a
  controlled isolated speedup. There is no p95 latency, statistical uncertainty,
  cluster-cost or executor-memory report yet.
- The workload excludes secure XML ingestion, XSD/TVS validation, real bank file
  variants, Delta writes/merges, Kafka, cloud storage, network latency,
  reconciliation state across multiple batches, and user-facing exception
  management.
- No Azure Databricks run, serverless costing, production SLA, 10M-row distributed
  cluster run, or tested transaction-level exactly-once guarantee is claimed.
- `check_id_uniqueness=False` is only safe when the upstream canonical tables
  enforce physical unique IDs independently. The default remains **True**.
- This is an operational reconciliation library. A match is **not** a proof of
  settlement, authorization, fraud-free processing or EPC scheme compliance.

## Run locally

```bash
pip install -e '.[spark]'
spark-submit --master 'local[2]' --conf spark.sql.shuffle.partitions=8 \
  benchmarks/spark_reconciliation.py --records 1000000
spark-submit --master 'local[2]' --conf spark.sql.shuffle.partitions=8 \
  benchmarks/spark_adversarial.py --records 1000000
```

## Next performance gates

Test the same suite against supported Spark 3.4/3.5 and Databricks runtimes,
with a documented cluster configuration and at least three repeated runs per
case. Record stages, shuffle and spill metrics, memory, Delta I/O and
cost-per-million. Include varying partition counts, payment-key skew,
cohort boundaries and deliberately malformed input.
