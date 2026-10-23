"""Regression tests for the public Scoop install workflow resolver."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/hermes-desktop-light-scoop-install.yml"


class ScoopInstallWorkflowTests(unittest.TestCase):
    def test_resolver_selects_newest_writeback_artifact(self):
        """An API response is not ordered, so the newest channel artifact wins."""
        old_canary = "a" * 40
        new_stable = "b" * 40
        artifacts = {
            "artifacts": [
                {
                    "id": 101,
                    "name": "hermes-desktop-light-canary-written-back-sha",
                    "expired": False,
                    "created_at": "2026-10-23T10:00:00Z",
                },
                {
                    "id": 202,
                    "name": "hermes-desktop-light-stable-written-back-sha",
                    "expired": False,
                    "created_at": "2026-10-23T11:00:00Z",
                },
            ]
        }
        workflow = WORKFLOW.read_text(encoding="utf-8")
        start = workflow.index("  resolve-published:")
        start = workflow.index("        run: |\n", start) + len("        run: |\n")
        end = workflow.index("\n\n  verify-public-scoop-install:", start)
        resolver = textwrap.dedent(workflow[start:end])

        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            fixture = root / "artifacts.json"
            fixture.write_text(json.dumps(artifacts), encoding="utf-8")
            gh = root / "gh"
            gh.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    if [[ "$1" == "api" ]]; then
                      endpoint="$2"
                      if [[ "$endpoint" == *"/artifacts?"* ]]; then
                        filter=""
                        while [[ $# -gt 0 ]]; do
                          if [[ "$1" == "--jq" ]]; then filter="$2"; shift 2; else shift; fi
                        done
                        jq -r "$filter" "$GH_ARTIFACTS"
                      elif [[ "$endpoint" == *"/contents/bucket/"* ]]; then
                        exit 0
                      else
                        echo "unexpected gh api endpoint: $endpoint" >&2
                        exit 1
                      fi
                    elif [[ "$1" == "run" && "$2" == "download" ]]; then
                      shift 2
                      name=""
                      directory=""
                      while [[ $# -gt 0 ]]; do
                        case "$1" in
                          --name) name="$2"; shift 2 ;;
                          --dir) directory="$2"; shift 2 ;;
                          *) shift ;;
                        esac
                      done
                      mkdir -p "$directory"
                      if [[ "$name" == *stable* ]]; then
                        printf '%s\\n' "$GH_NEW_STABLE" > "$directory/written-back-sha.txt"
                      else
                        printf '%s\\n' "$GH_OLD_CANARY" > "$directory/written-back-sha.txt"
                      fi
                    else
                      echo "unexpected gh invocation: $*" >&2
                      exit 1
                    fi
                    """
                ),
                encoding="utf-8",
            )
            gh.chmod(0o755)
            output = root / "github-output"
            environment = {
                **os.environ,
                "PATH": f"{root}{os.pathsep}{os.environ['PATH']}",
                "GH_ARTIFACTS": str(fixture),
                "GH_OLD_CANARY": old_canary,
                "GH_NEW_STABLE": new_stable,
                "GH_TOKEN": "test-token",
                "EVENT_NAME": "workflow_run",
                "WORKFLOW_RUN_ID": "123",
                "GITHUB_REPOSITORY": "takano536/scoop-bucket",
                "GITHUB_OUTPUT": str(output),
            }
            result = subprocess.run(
                ["bash", "-c", resolver],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
            )
            output_text = output.read_text(encoding="utf-8") if output.exists() else ""

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"sha={new_stable}", output_text)
        self.assertNotIn(f"sha={old_canary}", output_text)



if __name__ == "__main__":
    unittest.main()
