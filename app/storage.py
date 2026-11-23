"""S3-compatible storage (MinIO in docker-compose) with a local-folder backend for tests. Returns download links."""
import os
import shutil
from functools import lru_cache

from .config import get_settings


class LocalStorage:
    def __init__(self, root, base_url):
        self.root, self.base_url = os.path.abspath(root), base_url
        os.makedirs(self.root, exist_ok=True)

    def _p(self, key):
        p = os.path.abspath(os.path.join(self.root, key))
        if not p.startswith(self.root + os.sep):
            raise ValueError("bad key")
        return p

    def put_file(self, key, path, content_type=None):
        dst = self._p(key)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(path, dst)

    def get_file(self, key, dest):
        shutil.copyfile(self._p(key), dest)

    def url(self, key):
        return f"{self.base_url}/files/{key}"

    def local_path(self, key):
        return self._p(key)

    def ready(self):
        return os.path.isdir(self.root)


class S3Storage:
    def __init__(self, s):
        import boto3
        from botocore.config import Config
        cfg = Config(signature_version="s3v4", s3={"addressing_style": "path"})
        kw = dict(aws_access_key_id=s.s3_access_key, aws_secret_access_key=s.s3_secret_key, region_name=s.s3_region, config=cfg)
        self.s3 = boto3.client("s3", endpoint_url=s.s3_endpoint_url, **kw)
        self.signer = boto3.client("s3", endpoint_url=s.s3_public_endpoint_url, **kw)   # only used to sign browser-facing links
        self.bucket, self.expiry = s.s3_bucket, s.link_expiry_s
        self.ensure_bucket()

    def ensure_bucket(self):
        try:
            self.s3.head_bucket(Bucket=self.bucket)
        except Exception:
            self.s3.create_bucket(Bucket=self.bucket)

    def put_file(self, key, path, content_type=None):
        extra = {"ContentType": content_type} if content_type else {}
        self.s3.upload_file(path, self.bucket, key, ExtraArgs=extra)

    def get_file(self, key, dest):
        self.s3.download_file(self.bucket, key, dest)

    def url(self, key):
        return self.signer.generate_presigned_url("get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=self.expiry)

    def ready(self):
        self.s3.head_bucket(Bucket=self.bucket)
        return True


@lru_cache
def get_storage():
    s = get_settings()
    if s.storage_backend == "s3":
        return S3Storage(s)
    return LocalStorage(s.local_storage_dir, s.public_base_url)
