import asyncio
from pathlib import Path

from app.config import Settings
from app.database import Database
from app.operator.schemas import DesktopActionRequest, FriendConsentRequest, MemoryDeleteRequest, MessageRequest, OperatorPolicyRequest, PaymentRequest, VoiceTranscriptionRequest
from app.operator.service import OperatorService
from app.operator.vault import PrivateVault
from app.operator.desktop import DesktopResult


def make_operator(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-appdata"))
    db = Database(tmp_path / "operator.sqlite3")
    vault = PrivateVault("PavanPrivateAppTest")
    settings = Settings(_env_file=None)
    settings.openai_api_key = None
    return OperatorService(db, vault, settings), vault


def test_operator_starts_sleeping_and_vault_avoids_onedrive(tmp_path, monkeypatch):
    operator, vault = make_operator(tmp_path, monkeypatch)

    status = operator.status()

    assert status["mode"] == "Sleeping"
    assert status["wake_phrase"] == "Hey Chinna WakeUp"
    assert "OneDrive" not in status["vault_path"]
    assert status["private_mode"] is True
    assert Path(status["vault_path"]).exists()
    assert status["policy"]["supervision_mode"] == "supervised"
    assert status["policy"]["reasoning_mode"] == "hybrid"
    assert status["policy"]["payments_require_approval"] is True


def test_wake_sleep_and_observation_blocking(tmp_path, monkeypatch):
    operator, vault = make_operator(tmp_path, monkeypatch)

    blocked = operator.observe()
    awake = operator.wake("test")
    asleep = operator.sleep()

    assert blocked["ok"] is False
    assert awake["mode"] == "Listening"
    assert asleep["mode"] == "Sleeping"


def test_voice_wake_phrase_works_outside_dashboard(tmp_path, monkeypatch):
    operator, vault = make_operator(tmp_path, monkeypatch)
    operator.stop()
    monkeypatch.setattr(
        operator.desktop,
        "observe",
        lambda session_id=None: DesktopResult(True, "Observed desktop.", {"session_id": session_id}),
    )

    result = asyncio.run(operator.command("Hey Chinna wake up observe my screen"))

    assert result["status"]["mode"] == "Listening"
    assert result["reply"] == "Observed desktop."


def test_sensitive_desktop_action_requires_approval(tmp_path, monkeypatch):
    operator, vault = make_operator(tmp_path, monkeypatch)
    operator.wake("test")

    result = operator.desktop_action(
        DesktopActionRequest(action_type="run-command", command="git push origin main", confidence=100)
    )
    approvals = operator.pending_approvals()

    assert result["risk"] == "approval_required"
    assert result["approval_id"]
    assert approvals


def test_approved_desktop_action_executes_after_human_approval(tmp_path, monkeypatch):
    operator, vault = make_operator(tmp_path, monkeypatch)
    operator.wake("test")

    result = operator.desktop_action(DesktopActionRequest(action_type="click", x=10, y=20, confidence=30))
    monkeypatch.setattr(
        operator.desktop,
        "execute",
        lambda action: DesktopResult(True, f"Executed {action.action_type}.", {"x": action.x, "y": action.y}),
    )
    approved = operator.approve(result["approval_id"], True)

    assert approved["ok"] is True
    assert approved["data"] == {"x": 10, "y": 20}


def test_friend_voice_requires_consent_record(tmp_path, monkeypatch):
    operator, vault = make_operator(tmp_path, monkeypatch)
    consent_clip = tmp_path / "consent.wav"
    consent_clip.write_bytes(b"RIFFdemo")

    result = operator.save_friend_consent(
        FriendConsentRequest(
            friend_name="Demo Friend",
            consent_note="I allow local voice profile use for Chinna.",
            consent_clip_path=str(consent_clip),
        )
    )

    assert result["status"] == "consent-stored"
    assert Path(result["vault_record_path"]).exists()
    assert operator.friend_voice_status()["consent_saved"] is True


def test_friend_voice_missing_clip_is_rejected(tmp_path, monkeypatch):
    operator, vault = make_operator(tmp_path, monkeypatch)

    result = operator.save_friend_consent(
        FriendConsentRequest(
            friend_name="Demo Friend",
            consent_note="I allow local voice profile use for Chinna.",
            consent_clip_path=str(tmp_path / "missing.wav"),
        )
    )

    assert result["status"] == "consent-clip-missing"


def test_privacy_delete_wipes_vault_records(tmp_path, monkeypatch):
    operator, vault = make_operator(tmp_path, monkeypatch)
    vault.store_json("test", "sample", {"hello": "world"})

    before = operator.vault_status()["records"]
    deleted = operator.memory_delete(MemoryDeleteRequest(kind="all"))
    after = operator.vault_status()["records"]

    assert before >= 1
    assert deleted["deleted"] >= 1
    assert after == 0


def test_privacy_export_creates_local_zip(tmp_path, monkeypatch):
    operator, vault = make_operator(tmp_path, monkeypatch)
    vault.store_json("test", "sample", {"hello": "world"})

    result = operator.privacy_export()

    assert result["ok"] is True
    assert Path(result["export_path"]).exists()
    assert result["export_path"].endswith(".zip")


def test_voice_transcription_invalid_payload_fails_safely(tmp_path, monkeypatch):
    operator, vault = make_operator(tmp_path, monkeypatch)
    operator.wake("test")

    result = operator.transcribe_voice(VoiceTranscriptionRequest(audio_base64="not-valid-audio"))

    assert result["status"] == "failed"
    assert result["local"] is True


def test_save_operator_policy_allows_hybrid_and_local_only(tmp_path, monkeypatch):
    operator, vault = make_operator(tmp_path, monkeypatch)

    saved = operator.save_operator_policy(OperatorPolicyRequest(reasoning_mode="local-only"))

    assert saved["reasoning_mode"] == "local-only"
    assert saved["supervision_mode"] == "supervised"
    assert saved["messages_require_approval"] is True


def test_prepare_whatsapp_message_requires_approval(tmp_path, monkeypatch):
    operator, vault = make_operator(tmp_path, monkeypatch)
    operator.wake("test")

    result = operator.prepare_message(MessageRequest(recipient="+919999999999", message="hello there"))

    assert result["status"] == "pending-approval"
    assert result["approval_id"]


def test_natural_command_routes_to_whatsapp_message(tmp_path, monkeypatch):
    operator, vault = make_operator(tmp_path, monkeypatch)
    operator.wake("test")

    result = asyncio.run(operator.command("send whatsapp message to +919999999999 saying hello there"))

    assert "Prepared WhatsApp message" in result["reply"]
    assert operator.pending_approvals()


def test_payment_approval_executes_supervised_payment(tmp_path, monkeypatch):
    operator, vault = make_operator(tmp_path, monkeypatch)
    operator.wake("test")
    payload = PaymentRequest(app="GPay", recipient="Ravi", amount=500, upi_id="ravi@oksbi", note="Lunch")
    result = operator.prepare_payment(payload)
    monkeypatch.setattr(
        operator.desktop,
        "start_supervised_payment",
        lambda action: DesktopResult(True, "Opened payment flow.", {"recipient": action["recipient"], "amount": action["amount"]}),
    )

    approved = operator.approve(result["approval_id"], True)

    assert approved["ok"] is True
    assert approved["message"] == "Opened payment flow."
    assert approved["data"] == {"recipient": "Ravi", "amount": 500.0}


def test_indexed_folders_reject_sensitive_paths(tmp_path, monkeypatch):
    operator, vault = make_operator(tmp_path, monkeypatch)
    blocked = Path.home() / ".ssh"
    blocked.mkdir(parents=True, exist_ok=True)
    safe = tmp_path / "Projects"
    safe.mkdir(parents=True, exist_ok=True)

    folders = operator.save_indexed_folders([str(blocked), str(safe)])
    approved = {entry["path"] for entry in folders if entry["status"] == "approved"}

    assert str(safe.resolve()) in approved
    assert str(blocked.resolve()) not in approved
