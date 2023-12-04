## v0.2.8 (2023-12-04)

### Fix

- add missing awscli plugin for asdf

## v0.2.7 (2023-12-04)

### Fix

- move lambda code bundling to top level to prevent duplicate creations
- fix package name

## v0.2.6 (2023-11-14)

### Fix

- remove duplicate permission that was causing a circular dependency

## v0.2.5 (2023-11-14)

### Fix

- toggle feature flag to prevent circular dependency with the kms key and the sns topic

## v0.2.4 (2023-11-14)

### Fix

- fix incorrect property access

## v0.2.3 (2023-11-14)

### Fix

- load secrets from secrets manager instead of systems manager parameter store

## v0.2.2 (2023-11-13)

### Fix

- modify poetry install to not include dev dependencies and not install the root package

## v0.2.1 (2023-11-13)

### Fix

- fix the name of the context variable for the codeartifact authorization token

## v0.2.0 (2023-11-13)

### Feat

- initialize commitizen for project
- refactor to use cdk pipelines
- add python dependencies
- initial import
