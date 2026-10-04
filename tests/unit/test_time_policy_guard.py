"""No code may create instants outside ``oah.timeutil`` (the unified time policy)."""
import re

from oah.paths import repo_path

FORBIDDEN = re.compile(
    r"datetime\.now\(|datetime\.utcnow\(|utcfromtimestamp\(|\btime\.time\(\)|\btime\.strftime\(|\btime\.gmtime\("
)


def test_instants_are_only_created_by_the_unified_time_module():
    offenders = []
    for root in ("src", "scripts"):
        for file in repo_path(root).rglob("*.py"):
            if file.name == "timeutil.py":
                continue
            for number, line in enumerate(file.read_text(encoding="utf-8").splitlines(), start=1):
                if FORBIDDEN.search(line):
                    offenders.append(f"{file.name}:{number}: {line.strip()[:80]}")
    assert not offenders, "use oah.timeutil.utc_now / format_utc instead:\n" + "\n".join(offenders)
