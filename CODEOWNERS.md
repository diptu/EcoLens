# CODEOWNERS — ecoLens
# Each line is a file pattern followed by one or more owners.
# Order matters: later patterns override earlier ones.

# Default owners — every PR gets a review from one of these.
/                                          @diptu

# ML / modeling
/src/ecolens/ml/                           @diptu
/dbt/ecolens/                              @diptu
/mlflow/                                   @diptu
/notebooks/                                @diptu
/docs/model-card.md                        @diptu

# Backend
/src/ecolens/api/                          @diptu
/src/ecolens/db/                           @diptu
/src/ecolens/cache/                        @diptu
/src/ecolens/pipeline/                     @diptu

# Frontend
/frontend/                                 @diptu

# Infrastructure & security
/infra/                                    @diptu
/.github/                                  @diptu
/SECURITY.md                               @diptu

# Documentation
/docs/                                     @diptu
/README.md                                 @diptu
