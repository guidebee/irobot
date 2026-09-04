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

from ..model import Action, EventKind, GameplaySession, PrimitiveEvent, Project, SessionSegment

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


@unittest.skipUnless(HAVE_YAML, "PyYAML not installed")
class SessionIoTest(unittest.TestCase):
    def test_save_then_load_round_trip(self):
        session = GameplaySession(
            name="playthrough_1", source="device", reference_width=1080, reference_height=2400,
            events=[PrimitiveEvent(kind=EventKind.TAP, x=5, y=5)],
            segments=[SessionSegment(start_index=0, end_index=1, action_name="tap_a", label="tap")],
        )

        with tempfile.TemporaryDirectory() as tmp:
            project_path = Path(tmp) / "project.yaml"
            written_path = project_io.save_session(session, project_path)
            self.assertEqual(written_path, project_io.sessions_dir(project_path) / "playthrough_1.session.yaml")
            self.assertEqual(project_io.list_sessions(project_path), [written_path])
            restored = project_io.load_session(written_path)

        self.assertEqual(restored.name, "playthrough_1")
        self.assertEqual(len(restored.events), 1)
        self.assertEqual(restored.segments[0].action_name, "tap_a")

    def test_list_sessions_empty_when_no_recordings_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_path = Path(tmp) / "project.yaml"
            self.assertEqual(project_io.list_sessions(project_path), [])


if __name__ == "__main__":
    unittest.main()
