{#
  Standard dbt override (see dbt docs' "Custom schema" recipe): a
  model's `+schema:` config is used *verbatim* as the target schema,
  instead of dbt's default `<connection_schema>_<custom_schema>`
  concatenation. This project pre-provisions one schema per layer
  (raw, staging, intermediate, ml, analytics) on the warehouse Postgres
  -- concatenating the profile's default schema onto every one of them
  would just produce schemas nothing else expects (e.g. `public_staging`
  instead of `staging`).

  A model with no `+schema:` config (seeds, currently) still falls back
  to the connection's default schema, same as dbt's own default macro.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
