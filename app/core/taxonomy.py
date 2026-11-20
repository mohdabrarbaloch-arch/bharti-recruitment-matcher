"""Skill taxonomy: canonical names, aliases, and the related-skill graph.

The point of this module is that "React" and "React.js" and "reactjs" are the
same skill, while "React" and "Vue" are *not* the same skill but are close
enough that a Vue developer deserves partial credit for a React requirement.

Everything here is data plus pure functions. No I/O, no database, no config.
That is deliberate: the matching logic is the part most likely to be wrong, so
it has to be testable in microseconds.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# --------------------------------------------------------------------------
# Canonical skills
# --------------------------------------------------------------------------

#: canonical name -> (category, aliases)
#: Aliases are matched case-insensitively on word boundaries. Keep them
#: specific: a bare "go" would match "Google", so the alias list for Go
#: contains "golang" and "go lang" but not "go".
_SKILL_TABLE: dict[str, tuple[str, tuple[str, ...]]] = {
    # --- languages ---
    "python": ("language", ("python", "python3", "py")),
    "javascript": ("language", ("javascript", "js", "ecmascript", "es6")),
    "typescript": ("language", ("typescript", "ts")),
    "java": ("language", ("java", "java8", "java11", "java17")),
    "csharp": ("language", ("c#", "csharp", "c sharp", ".net c#")),
    "cpp": ("language", ("c++", "cpp")),
    "go": ("language", ("golang", "go lang")),
    "rust": ("language", ("rust", "rustlang")),
    "ruby": ("language", ("ruby", "ruby on rails", "rails")),
    "php": ("language", ("php", "php8")),
    "kotlin": ("language", ("kotlin",)),
    "swift": ("language", ("swift", "swiftui")),
    "sql": ("language", ("sql", "t-sql", "plsql", "pl/sql")),
    "r": ("language", ("r language", "rstudio")),
    "scala": ("language", ("scala",)),
    "dart": ("language", ("dart",)),
    # --- frontend ---
    "react": ("frontend", ("react", "react.js", "reactjs", "react js")),
    "vue": ("frontend", ("vue", "vue.js", "vuejs", "vue js", "nuxt")),
    "angular": ("frontend", ("angular", "angularjs", "angular.js")),
    "svelte": ("frontend", ("svelte", "sveltekit")),
    "nextjs": ("frontend", ("next.js", "nextjs", "next js")),
    "html": ("frontend", ("html", "html5")),
    "css": ("frontend", ("css", "css3", "scss", "sass", "less")),
    "tailwind": ("frontend", ("tailwind", "tailwindcss", "tailwind css")),
    "redux": ("frontend", ("redux", "redux toolkit", "rtk")),
    "webpack": ("frontend", ("webpack", "vite", "rollup", "esbuild")),
    # --- backend ---
    "nodejs": ("backend", ("node", "node.js", "nodejs", "node js")),
    "django": ("backend", ("django", "django rest framework", "drf")),
    "flask": ("backend", ("flask",)),
    "fastapi": ("backend", ("fastapi", "fast api")),
    "spring": ("backend", ("spring", "spring boot", "springboot")),
    "express": ("backend", ("express", "express.js", "expressjs")),
    "graphql": ("backend", ("graphql", "apollo")),
    "rest": ("backend", ("rest", "rest api", "restful", "rest apis")),
    "grpc": ("backend", ("grpc", "protobuf", "protocol buffers")),
    "microservices": ("backend", ("microservices", "microservice", "service oriented")),
    # --- data / ml ---
    "pandas": ("data", ("pandas",)),
    "numpy": ("data", ("numpy",)),
    "pytorch": ("data", ("pytorch", "torch")),
    "tensorflow": ("data", ("tensorflow", "tf.keras", "keras")),
    "scikit": ("data", ("scikit-learn", "sklearn", "scikit learn")),
    "spark": ("data", ("spark", "pyspark", "apache spark")),
    "airflow": ("data", ("airflow", "apache airflow", "dbt")),
    "kafka": ("data", ("kafka", "apache kafka", "rabbitmq", "pub/sub")),
    "etl": ("data", ("etl", "elt", "data pipeline", "data pipelines")),
    "llm": (
        "data",
        (
            "llm",
            "llms",
            "large language model",
            "large language models",
            "gpt",
            "openai api",
        ),
    ),
    "rag": (
        "data",
        ("rag", "retrieval augmented generation", "vector search", "embeddings"),
    ),
    "nlp": ("data", ("nlp", "natural language processing", "text classification")),
    "computer_vision": ("data", ("computer vision", "opencv", "image classification")),
    "mlops": ("data", ("mlops", "model deployment", "model serving", "mlflow")),
    # --- databases ---
    "postgres": ("database", ("postgres", "postgresql", "psql")),
    "mysql": ("database", ("mysql", "mariadb")),
    "mongodb": ("database", ("mongodb", "mongo")),
    "redis": ("database", ("redis", "memcached")),
    "elasticsearch": ("database", ("elasticsearch", "opensearch", "elastic search")),
    "sqlite": ("database", ("sqlite", "sqlite3")),
    # --- cloud / devops ---
    "aws": ("cloud", ("aws", "amazon web services", "ec2", "s3", "lambda")),
    "gcp": ("cloud", ("gcp", "google cloud", "bigquery", "cloud run")),
    "azure": ("cloud", ("azure", "microsoft azure")),
    "docker": ("devops", ("docker", "container", "containers", "containerization")),
    "kubernetes": ("devops", ("kubernetes", "k8s", "helm", "eks", "gke")),
    "terraform": ("devops", ("terraform", "infrastructure as code", "iac", "pulumi")),
    "ci_cd": (
        "devops",
        (
            "ci/cd",
            "cicd",
            "continuous integration",
            "github actions",
            "jenkins",
            "gitlab ci",
        ),
    ),
    "linux": ("devops", ("linux", "ubuntu", "debian", "bash", "shell scripting")),
    "monitoring": (
        "devops",
        ("prometheus", "grafana", "datadog", "observability", "monitoring"),
    ),
    # --- product / design ---
    "figma": ("design", ("figma", "sketch", "adobe xd")),
    "ui_design": (
        "design",
        (
            "ui design",
            "ui/ux",
            "ux design",
            "user experience",
            "wireframing",
            "prototyping",
        ),
    ),
    "design_systems": (
        "design",
        ("design system", "design systems", "component library"),
    ),
    "accessibility": ("design", ("accessibility", "a11y", "wcag")),
    # --- growth / marketing ---
    "seo": ("growth", ("seo", "search engine optimization", "technical seo")),
    "analytics": (
        "growth",
        ("google analytics", "ga4", "mixpanel", "amplitude", "product analytics"),
    ),
    "ab_testing": (
        "growth",
        ("a/b testing", "ab testing", "split testing", "experimentation"),
    ),
    "paid_ads": (
        "growth",
        ("google ads", "meta ads", "facebook ads", "ppc", "paid social"),
    ),
    "content": ("growth", ("content marketing", "copywriting", "content strategy")),
    # --- process ---
    "agile": ("process", ("agile", "scrum", "kanban", "sprint planning")),
    "testing": (
        "process",
        (
            "unit testing",
            "pytest",
            "jest",
            "tdd",
            "test automation",
            "playwright",
            "cypress",
        ),
    ),
    "git": ("process", ("git", "github", "gitlab", "version control")),
    "code_review": ("process", ("code review", "code reviews", "pair programming")),
    "mentoring": ("process", ("mentoring", "mentorship", "coaching", "team lead")),
}

#: Related-skill graph. Symmetric pairs with a partial-credit factor.
#: A candidate who has the left skill gets `factor` credit toward the right.
#: Deliberately conservative: 0.35-0.5, never above 0.5, because "I know Vue"
#: is genuinely not "I know React" and pretending otherwise wastes interviews.
_RELATED: dict[str, dict[str, float]] = {
    "react": {"vue": 0.45, "angular": 0.40, "svelte": 0.40},
    "vue": {"react": 0.45, "angular": 0.40, "svelte": 0.45},
    "angular": {"react": 0.40, "vue": 0.40},
    "svelte": {"react": 0.40, "vue": 0.45},
    "nextjs": {"react": 0.50},
    "javascript": {"typescript": 0.50},
    "typescript": {"javascript": 0.50},
    "django": {"flask": 0.45, "fastapi": 0.40},
    "flask": {"django": 0.45, "fastapi": 0.50},
    "fastapi": {"flask": 0.50, "django": 0.40},
    "express": {"nodejs": 0.50},
    "nodejs": {"express": 0.50},
    "postgres": {"mysql": 0.50, "sqlite": 0.40},
    "mysql": {"postgres": 0.50, "sqlite": 0.40},
    "mongodb": {"postgres": 0.30},
    "aws": {"gcp": 0.45, "azure": 0.45},
    "gcp": {"aws": 0.45, "azure": 0.40},
    "azure": {"aws": 0.45, "gcp": 0.40},
    "pytorch": {"tensorflow": 0.45},
    "tensorflow": {"pytorch": 0.45},
    "pandas": {"numpy": 0.40},
    "numpy": {"pandas": 0.40},
    "kubernetes": {"docker": 0.40},
    "docker": {"kubernetes": 0.35},
    "terraform": {"ci_cd": 0.30},
    "llm": {"rag": 0.45, "nlp": 0.40},
    "rag": {"llm": 0.45},
    "nlp": {"llm": 0.40},
    "ui_design": {"figma": 0.45, "design_systems": 0.40},
    "figma": {"ui_design": 0.45},
    "seo": {"content": 0.35},
    "content": {"seo": 0.35},
    "analytics": {"ab_testing": 0.40},
    "ab_testing": {"analytics": 0.40},
    "java": {"kotlin": 0.40, "scala": 0.35},
    "kotlin": {"java": 0.40},
    "csharp": {"java": 0.30},
    "go": {"rust": 0.30},
    "rust": {"go": 0.30},
    "ruby": {"python": 0.30},
    "php": {"python": 0.25},
}

#: Aliases that are too short or too common to match safely outside a
#: dedicated skills section. "py" inside prose is usually a typo, "ts" is
#: usually a timestamp. We still accept them when they appear in a
#: comma-separated skills list, where the context makes them unambiguous.
_AMBIGUOUS_ALIASES = frozenset({"py", "ts", "js", "r language", "go lang"})


@dataclass(frozen=True)
class Skill:
    """A canonical skill with everything needed to match and explain it."""

    name: str
    category: str
    aliases: tuple[str, ...]
    related: dict[str, float] = field(default_factory=dict)

    @property
    def label(self) -> str:
        """Human-facing label. Underscores read badly in a UI."""
        return self.name.replace("_", " ").title()


def _build_index() -> dict[str, str]:
    """alias (lowercased) -> canonical name."""
    index: dict[str, str] = {}
    for canonical, (_category, aliases) in _SKILL_TABLE.items():
        index[canonical] = canonical
        for alias in aliases:
            index[alias.lower()] = canonical
    return index


_ALIAS_INDEX = _build_index()

#: Longest aliases first, so "react.js" is tried before "react" and
#: "google cloud" before "google". Without this, a shorter alias can consume
#: the prefix of a longer one and leave a dangling fragment behind.
_ALIASES_BY_LENGTH: tuple[str, ...] = tuple(sorted(_ALIAS_INDEX, key=len, reverse=True))


def all_skills() -> list[Skill]:
    """Every canonical skill, sorted by name. Used by the API for autocomplete."""
    return [
        Skill(
            name=name,
            category=category,
            aliases=aliases,
            related=dict(_RELATED.get(name, {})),
        )
        for name, (category, aliases) in sorted(_SKILL_TABLE.items())
    ]


def canonical(name: str) -> str | None:
    """Resolve any alias to its canonical skill name, or None if unknown."""
    return _ALIAS_INDEX.get(name.strip().lower())


def skill(name: str) -> Skill | None:
    """Look up a Skill object by canonical name or alias."""
    resolved = canonical(name)
    if resolved is None:
        return None
    category, aliases = _SKILL_TABLE[resolved]
    return Skill(
        name=resolved,
        category=category,
        aliases=aliases,
        related=dict(_RELATED.get(resolved, {})),
    )


def related_credit(owned: str, wanted: str) -> float:
    """Partial credit that `owned` gives toward `wanted`, in [0, 1].

    Returns 1.0 for an exact match, the graph factor for a related skill,
    and 0.0 otherwise. The graph is treated as symmetric even where only one
    direction is written down, because a one-way edge is almost always an
    oversight rather than a deliberate asymmetry.
    """
    if owned == wanted:
        return 1.0
    direct = _RELATED.get(owned, {}).get(wanted)
    if direct is not None:
        return direct
    reverse = _RELATED.get(wanted, {}).get(owned)
    if reverse is not None:
        return reverse
    return 0.0


def _alias_pattern(alias: str) -> re.Pattern[str]:
    """Word-boundary pattern for an alias.

    Aliases containing regex-special characters (c++, c#, .net) are escaped.
    Boundaries are only applied where the alias edge is alphanumeric, so
    "c++" still matches inside "C++ developer" without requiring a boundary
    after the plus signs.
    """
    escaped = re.escape(alias)
    left = r"(?<![a-z0-9])" if alias[0].isalnum() else ""
    right = r"(?![a-z0-9])" if alias[-1].isalnum() else ""
    return re.compile(left + escaped + right, re.IGNORECASE)


_PATTERN_CACHE: dict[str, re.Pattern[str]] = {}


def _pattern(alias: str) -> re.Pattern[str]:
    cached = _PATTERN_CACHE.get(alias)
    if cached is None:
        cached = _alias_pattern(alias)
        _PATTERN_CACHE[alias] = cached
    return cached


def extract_skills(text: str, *, strict: bool = True) -> dict[str, str]:
    """Find every canonical skill mentioned in `text`.

    Returns canonical name -> the alias that matched, so the UI can show
    *why* a skill was detected ("matched 'reactjs'").

    With ``strict=True`` (the default) ambiguous short aliases are skipped,
    which is what you want when scanning free prose. Pass ``strict=False``
    for a comma-separated skills list, where "js" and "ts" are unambiguous.
    """
    found: dict[str, str] = {}
    for alias in _ALIASES_BY_LENGTH:
        if strict and alias in _AMBIGUOUS_ALIASES:
            continue
        if _pattern(alias).search(text):
            canonical_name = _ALIAS_INDEX[alias]
            # Keep the first (longest) alias that matched: it is the most
            # specific evidence, and it is what we want to show the user.
            found.setdefault(canonical_name, alias)
    return found


def split_skill_list(text: str) -> list[str]:
    """Split a comma/slash/pipe separated skills line into raw tokens."""
    parts = re.split(r"[,;|/•·\n\t]+", text)
    return [p.strip(" .-–—") for p in parts if p.strip(" .-–—")]


def normalise_skill_list(raw: list[str]) -> list[str]:
    """Map a list of user-supplied skill strings to canonical names.

    Unknown skills are kept as lowercased free text rather than dropped, so a
    recruiter asking for "Solidity" still gets a requirement row even though
    the taxonomy has never heard of it. It simply cannot earn related credit.
    """
    out: list[str] = []
    for item in raw:
        resolved = canonical(item)
        value = resolved if resolved else item.strip().lower()
        if value and value not in out:
            out.append(value)
    return out
