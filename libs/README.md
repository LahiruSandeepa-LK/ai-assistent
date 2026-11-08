# libs/

Shared internal packages imported by every service (see docs/01-system-architecture.md §5).
Services never import each other; they share only through these packages and HTTP.
