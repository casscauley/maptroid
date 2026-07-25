# Media on DigitalOcean Spaces (see ../../../maptroid-do-spaces.md).
# Uploads live at s3://skade/maptroid/... and are public-read.
# Requires DIGITAL_OCEAN_SPACES_KEY/SECRET, loaded from the repo-root .env by
# settings/__init__.py; falls back to local filesystem storage when they are not
# defined, so a fresh checkout still runs.
#
# IMPORTANT — this only affects FileField/ImageField, i.e. anything saved through
# Django's storage API. maptroid also writes ~23G directly to MEDIA_ROOT with
# mkdir + PIL.save (sm_zone, sm_cache, labbooks, deepzoom). Those bypass storage
# entirely and are still served from local disk by nginx's /media/ alias, which
# is why that alias must stay. See the spec's "track 3" for that half.
DIGITAL_OCEAN_SPACES_KEY = os.environ.get("DIGITAL_OCEAN_SPACES_KEY")
DIGITAL_OCEAN_SPACES_SECRET = os.environ.get("DIGITAL_OCEAN_SPACES_SECRET")

if DIGITAL_OCEAN_SPACES_KEY:
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                "access_key": DIGITAL_OCEAN_SPACES_KEY,
                "secret_key": DIGITAL_OCEAN_SPACES_SECRET,
                "bucket_name": "skade",
                "region_name": "nyc3",
                "endpoint_url": "https://nyc3.digitaloceanspaces.com",
                "location": "maptroid",     # key becomes maptroid/<upload_to>/<file>
                "default_acl": "public-read",
                "file_overwrite": False,
                "querystring_auth": False,  # public objects, no signed URLs
                "custom_domain": "skade.nyc3.cdn.digitaloceanspaces.com",
            },
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
    # Only the storage-managed half moves. MEDIA_ROOT stays as it is so the
    # direct-write pipeline and nginx keep working on the other 23G.
    MEDIA_URL = "https://skade.nyc3.cdn.digitaloceanspaces.com/maptroid/"
