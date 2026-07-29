{#
  Root TODO.md's "Anomaly Detection" section: shared aggregation/merge
  helpers for `anomaly_score`/`anomaly_flags`/`anomaly_explanation` --
  see int_energy_unified_30min.sql's own header comment for the full
  "why max, not average" reasoning. Centralised here since both that
  model (4 separate `group by` buckets) and int_energy_with_weather.sql
  (a cross-source join) need the identical "worst wins, and its
  flags/explanation come along with it" rule.
#}

{#
  For a `group by` bucket combining several raw rows (e.g. NEM's 5-min
  records rolled into one 30-min row) -- `array_agg(... order by
  anomaly_score desc nulls last))[1]` picks the flags/explanation
  belonging to whichever row in the bucket had the highest score, not a
  blended string that wouldn't describe any single real observation.
#}
{% macro worst_anomaly_agg() %}
    max(anomaly_score) as anomaly_score,
    (array_agg(anomaly_flags order by anomaly_score desc nulls last))[1] as anomaly_flags,
    (array_agg(anomaly_explanation order by anomaly_score desc nulls last))[1] as anomaly_explanation
{% endmacro %}

{#
  For a plain join combining exactly two already-one-row-per-key
  sources (e.g. `int_energy_with_weather`'s energy + weather join) --
  same "worst wins" rule as `worst_anomaly_agg()`, expressed as a scalar
  `case` instead of an aggregate since there's no `group by` here.
  `left`/`right` are the two sides' table aliases (as raw SQL text, not
  quoted identifiers) already carrying `anomaly_score`/`anomaly_flags`/
  `anomaly_explanation` columns.
#}
{% macro pick_worse_of_two(left, right) %}
    greatest(coalesce({{ left }}.anomaly_score, 0), coalesce({{ right }}.anomaly_score, 0)) as anomaly_score,
    case
        when coalesce({{ left }}.anomaly_score, 0) >= coalesce({{ right }}.anomaly_score, 0)
            then {{ left }}.anomaly_flags
        else {{ right }}.anomaly_flags
    end as anomaly_flags,
    case
        when coalesce({{ left }}.anomaly_score, 0) >= coalesce({{ right }}.anomaly_score, 0)
            then {{ left }}.anomaly_explanation
        else {{ right }}.anomaly_explanation
    end as anomaly_explanation
{% endmacro %}

{#
  Same rule again, for exactly three sources (NEM's own market +
  network-level fueltech + OpenElectricity fallback, all already
  one-row-per-key going into `nem_final`).
#}
{% macro pick_worse_of_three(a, b, c) %}
    greatest(
        coalesce({{ a }}.anomaly_score, 0), coalesce({{ b }}.anomaly_score, 0), coalesce({{ c }}.anomaly_score, 0)
    ) as anomaly_score,
    case
        when coalesce({{ a }}.anomaly_score, 0) >= greatest(coalesce({{ b }}.anomaly_score, 0), coalesce({{ c }}.anomaly_score, 0))
            then {{ a }}.anomaly_flags
        when coalesce({{ b }}.anomaly_score, 0) >= coalesce({{ c }}.anomaly_score, 0)
            then {{ b }}.anomaly_flags
        else {{ c }}.anomaly_flags
    end as anomaly_flags,
    case
        when coalesce({{ a }}.anomaly_score, 0) >= greatest(coalesce({{ b }}.anomaly_score, 0), coalesce({{ c }}.anomaly_score, 0))
            then {{ a }}.anomaly_explanation
        when coalesce({{ b }}.anomaly_score, 0) >= coalesce({{ c }}.anomaly_score, 0)
            then {{ b }}.anomaly_explanation
        else {{ c }}.anomaly_explanation
    end as anomaly_explanation
{% endmacro %}
