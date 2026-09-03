"""YAML round-trip test. Needs PyYAML (see requirements.txt); skipped if
it isn't installed rather than failing the whole suite for an unrelated
missing dependency."""
import tempfile
import unittest
from pathlib import Path

try:
    import yaml  # noqa: F401
    HAVE_YAML = True
except ImportError:
    HAVE_YAML = False

from ..model import Action, EventKind, PrimitiveEvent, Project

if HAVE_YAML:
    from .. import io as project_io


@unittest.skipUnless(HAVE_YAML, "PyYAML not installed")
class ProjectIoTest(unittest.TestCase):
    def test_save_then_load_round_trip(self):
        project = Project(name="game", host="127.0.0.1", port=27183,
                           reference_width=1080, reference_height=2400)
        project.add_action(Action(name="long_jump", events=[
            PrimitiveEvent(kind=EventKind.PRESS, x=1802, y=823, pointer_id=1),
            PrimitiveEvent(kind=EventKind.WAIT, pointer_id=1, frames=20),
            PrimitiveEvent(kind=EventKind.RELEASE, pointer_id=1),
        ]))

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "project.yaml"
            project_io.save_project(project, path)
            restored = project_io.load_project(path)

        self.assertEqual(restored.name, "game")
        self.assertEqual(restored.reference_width, 1080)
        events = restored.actions["long_jump"].events
        self.assertEqual([e.kind for e in events], [EventKind.PRESS, EventKind.WAIT, EventKind.RELEASE])
        self.assertEqual(events[1].frames, 20)


if __name__ == "__main__":
    unittest.main()
