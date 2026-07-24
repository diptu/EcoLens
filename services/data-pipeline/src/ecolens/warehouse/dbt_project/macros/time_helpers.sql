{#
  Everything in the warehouse stays in UTC until the very last step
  (see werehouse.md "Daylight saving time") -- these two macros are
  that last step, used only where a model needs a 30-min bucket key or
  a region's local calendar date.
#}

{% macro bucket_30min(column) %}
    (date_trunc('hour', {{ column }}) + floor(date_part('minute', {{ column }}) / 30) * interval '30 minutes')
{% endmacro %}

{% macro region_timezone_case(region_column) %}
    case {{ region_column }}
        when 'NSW1' then 'Australia/Sydney'
        when 'QLD1' then 'Australia/Brisbane'
        when 'VIC1' then 'Australia/Melbourne'
        when 'SA1' then 'Australia/Adelaide'
        when 'TAS1' then 'Australia/Hobart'
        when 'WEM' then 'Australia/Perth'
        else 'UTC'
    end
{% endmacro %}

{#
  Standard incremental "reprocess the last N days" cutoff, used by
  every incremental model in intermediate/. Reads the max grain-key
  timestamp already loaded into `this` and steps back `lookback_days`
  (default from dbt_project.yml vars) to catch late-arriving/revised
  source data (see werehouse.md "Late-arriving data").
#}
{% macro lookback_cutoff(days=none) %}
    {% set days = days or var('lookback_days', 5) %}
    (select coalesce(max(ts_30), '2000-01-01'::timestamptz) from {{ this }}) - interval '{{ days }} days'
{% endmacro %}
