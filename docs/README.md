# Project documentation

This directory contains versioned technical documentation for the application.
Private planning documents and design exports remain outside this repository
in the sibling `../doc/` folder.

## Module ownership

| Module | Responsibility |
| --- | --- |
| M1 | Repository conventions, architecture decisions and shared contracts |
| M2 | Frontend design system, dashboard panels and controls |
| M3 | Source register, validation and scheduled collection |
| M4 | Database schema, SQL, dashboard API and health contract |
| M5 | Authentication, secrets and CORS |
| M6 | Integration and quality verification |
| M7 | Deployment, operational documentation and submission |

## Naming conventions

- React components use PascalCase filenames; the frontend entrypoint is `main.tsx`.
- Python modules and functions use `snake_case`; the API entrypoint is `app/main.py`.
- Documentation filenames use lowercase words separated by hyphens.
- Commit titles follow `m<module>.f<feature>.<snake_case_name>`.

Architecture, source, API and deployment documentation will be added by their
owning modules as those decisions and implementations are verified.
