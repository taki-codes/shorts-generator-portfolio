"""Initial YouTube implementation: explicit account binding, private only, no scheduling."""
import ctypes
import json
import os
import re
import time
from pathlib import Path
from ctypes import wintypes
from .core import WorkflowError, read_json, write_json, now, sha

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"]


def token_path(profile):
    if os.name != "nt":
        raise WorkflowError("OAuth token storage is implemented for Windows DPAPI only")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}",profile):
        raise WorkflowError("Profile name must contain letters/numbers/-/_")
    folder = Path(os.environ["LOCALAPPDATA"]) / "OWShortKit" / "oauth"
    folder.mkdir(parents=True,exist_ok=True)
    return folder / (profile+".dpapi")


class Blob(ctypes.Structure):
    _fields_ = [("cbData",wintypes.DWORD),("pbData",ctypes.POINTER(ctypes.c_ubyte))]


def crypt(data,protect=True):
    if os.name != "nt":
        raise WorkflowError("Windows DPAPI required; no plaintext token fallback")
    array = (ctypes.c_ubyte*len(data)).from_buffer_copy(data)
    source,out = Blob(len(data),array),Blob()
    library = ctypes.WinDLL("crypt32",use_last_error=True)
    if protect:
        function = library.CryptProtectData
        function.argtypes = [ctypes.POINTER(Blob),wintypes.LPCWSTR,ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
        args = (ctypes.byref(source),"OWShortKit",None,None,None,1,ctypes.byref(out))
    else:
        function = library.CryptUnprotectData
        function.argtypes = [ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
        args = (ctypes.byref(source),None,None,None,None,1,ctypes.byref(out))
    function.restype = wintypes.BOOL
    if not function(*args):
        raise WorkflowError("DPAPI failed; use the same Windows user that authorized OAuth")
    try:
        return ctypes.string_at(out.pbData,out.cbData)
    finally:
        local_free = ctypes.WinDLL("kernel32").LocalFree
        local_free.argtypes = [ctypes.c_void_p]
        local_free.restype = ctypes.c_void_p
        local_free(out.pbData)


def save_credentials(profile,credentials):
    path = token_path(profile)
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(crypt(credentials.to_json().encode()))
    os.replace(temporary,path)


def authorize(client_secrets,profile):
    from google_auth_oauthlib.flow import InstalledAppFlow
    token_path(profile)  # Check secure storage before opening an OAuth flow.
    flow = InstalledAppFlow.from_client_secrets_file(client_secrets,SCOPES,autogenerate_code_verifier=True)
    credentials = flow.run_local_server(host="127.0.0.1",port=0,access_type="offline",prompt="consent select_account")
    save_credentials(profile,credentials)


def api(profile):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    path = token_path(profile)
    if not path.exists():
        raise WorkflowError("Run youtube-auth for this profile first")
    credentials = Credentials.from_authorized_user_info(json.loads(crypt(path.read_bytes(),False)),SCOPES)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request()); save_credentials(profile,credentials)
    if not credentials.valid:
        raise WorkflowError("OAuth is expired; authorize again")
    return build("youtube","v3",credentials=credentials,cache_discovery=False)


def channels(profile,service=None):
    service = service or api(profile)
    result = service.channels().list(part="id,snippet",mine=True).execute()
    return [{"id":x["id"],"title":x["snippet"]["title"]} for x in result.get("items",[])]


def require_channel(service,expected):
    authorized = channels(None,service)
    if expected not in [x["id"] for x in authorized]:
        raise WorkflowError("Authorized YouTube channel does not match --channel; choose the right account/Brand channel in OAuth")


def final_build(build):
    build = Path(build).resolve()
    manifest = read_json(build/"manifest.json")
    if manifest["stage"] != "final" or manifest["status"] != "RENDERED":
        raise WorkflowError("Only a successfully rendered final build can be uploaded")
    if read_json(build/"project.snapshot.json").get("synthetic_test"):
        raise WorkflowError("Synthetic test video cannot be uploaded by this kit")
    video = build/manifest["video"]
    if sha(video) != manifest["video_sha256"]:
        raise WorkflowError("Video changed after validation; render a new final build")
    return build,manifest,video


def upload(build,profile,channel_id,made_for_kids):
    from googleapiclient.http import MediaFileUpload
    from googleapiclient.errors import HttpError
    build,manifest,video = final_build(build)
    metadata = read_json(build/"metadata.json")
    if not metadata.get("title") or len(metadata["title"]) > 100:
        raise WorkflowError("YouTube title must contain 1..100 characters")
    description = metadata["description_with_credits"]+"\n"+" ".join(metadata.get("hashtags",[]))
    if len(description.encode("utf-8")) > 5000:
        raise WorkflowError("YouTube description exceeds 5000 UTF-8 bytes")
    service = api(profile)
    require_channel(service,channel_id)
    fingerprint = sha(video)
    journal = token_path(profile).parent / ("upload-"+channel_id+"-"+fingerprint+".json")
    if journal.exists():
        previous = read_json(journal)
        if previous.get("video_id"):
            write_json(build/"youtube-receipt.json",previous)
            return status(build/"youtube-receipt.json",profile,service)
        raise WorkflowError("This video already has an upload attempt with no known ID. Check Studio before retrying; automatic retry could duplicate it.")
    receipt = {"platform":"youtube","profile":profile,"channel_id":channel_id,"privacy_requested":"private",
               "video_sha256":fingerprint,"created_at":now(),"state":"INITIATING","video_id":None,
               "shorts_classification":"NOT_VERIFIED","made_for_kids":made_for_kids}
    receipt_path = build/"youtube-receipt.json"
    def persist():
        write_json(journal,receipt); write_json(receipt_path,receipt)
    persist()
    try:
        request = service.videos().insert(part="snippet,status",body={
            "snippet":{"title":metadata["title"],"description":description,"categoryId":"20","defaultLanguage":"ja"},
            "status":{"privacyStatus":"private","selfDeclaredMadeForKids":made_for_kids}},
            media_body=MediaFileUpload(str(video),mimetype="video/mp4",chunksize=8*1024*1024,resumable=True))
        receipt["state"] = "UPLOADING"; persist()
        response = None
        errors = 0
        while response is None:
            try:
                progress,response = request.next_chunk(num_retries=2)
                errors = 0
            except HttpError as e:
                if e.resp.status not in (429,500,502,503,504) or errors >= 3:
                    raise
                errors += 1; time.sleep(min(2**errors,8)); continue
            if progress:
                receipt["uploaded_fraction"] = round(progress.progress(),3); persist()
        receipt.update(video_id=response["id"],state="UPLOADED_PROCESSING",uploaded_at=now(),
                       confirmation_url=f"https://studio.youtube.com/video/{response['id']}/edit",
                       watch_url=f"https://www.youtube.com/watch?v={response['id']}")
        persist()
        observed = status(receipt_path,profile,service)
        write_json(journal,observed)
        return observed
    except Exception as e:
        receipt.update(state="CHECK_REQUIRED" if not receipt.get("video_id") else "STATUS_CHECK_FAILED",
                       failure_type=type(e).__name__,message="Upload/check interrupted. Check Studio before retrying.")
        persist()
        raise WorkflowError("YouTube upload/check failed; see youtube-receipt.json and Studio. No automatic new upload.") from e


def classify(item,expected_channel):
    if item.get("snippet",{}).get("channelId") != expected_channel:
        return "ACCOUNT_MISMATCH"
    s,p = item.get("status",{}),item.get("processingDetails",{})
    if s.get("uploadStatus") in ("failed","rejected","deleted") or p.get("processingStatus") in ("failed","terminated"):
        return "FAILED"
    if s.get("privacyStatus") != "private":
        return "PRIVACY_MISMATCH"
    if p.get("processingStatus") == "succeeded" or s.get("uploadStatus") == "processed":
        return "COMPLETE_PRIVATE"
    return "UPLOADED_PROCESSING"


def status(receipt_path,profile,service=None):
    receipt = read_json(receipt_path)
    if receipt.get("profile") != profile:
        raise WorkflowError("Receipt profile differs from requested profile")
    if not receipt.get("video_id"):
        raise WorkflowError("No known video ID; check Studio to resolve interrupted upload")
    service = service or api(profile)
    require_channel(service,receipt["channel_id"])
    r = service.videos().list(part="snippet,status,processingDetails",id=receipt["video_id"]).execute()
    if not r.get("items"):
        receipt.update(state="NOT_FOUND_OR_NOT_ACCESSIBLE",checked_at=now())
    else:
        item = r["items"][0]
        receipt.update(state=classify(item,receipt["channel_id"]),checked_at=now(),
                       observed_status=item.get("status",{}),processing=item.get("processingDetails",{}),observed_title=item["snippet"]["title"])
    write_json(receipt_path,receipt)
    return receipt
