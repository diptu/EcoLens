#!/bin/bash

# Create root directories
mkdir -p services/{forecast-api,data-pipeline,dashboard} \
         data/{raw,processed,external,schemas} \
         infra/{docker,prometheus,grafana/dashboards,k8s/{forecast-api,data-pipeline,dashboard}} \
         scripts docs/{runbooks,adr} \
         notebooks \
         .github/{workflows,ISSUE_TEMPLATE}

# Create Python service structures
for svc in forecast-api data-pipeline; do
  mkdir -p services/$svc/{src/ecolens,tests}
done

# Create specific sub-structures
mkdir -p services/data-pipeline/dbt/ecolens/models/{staging,intermediate,marts} \
         services/data-pipeline/dbt/ecolens/seeds \
         services/data-pipeline/mlflow/projects

# Create files (placeholders)
touch README.md LICENSE CONTRIBUTING.md CODE_OF_CONDUCT.md SECURITY.md CODEOWNERS \
      docker-compose.yml .env.example Makefile \
      services/forecast-api/pyproject.toml services/forecast-api/uv.lock \
      services/data-pipeline/pyproject.toml services/data-pipeline/uv.lock \
      .github/workflows/{ci.yml,ml-pipeline.yml,docker.yml,codeql.yml,release.yml}

echo "Project structure generated successfully."
