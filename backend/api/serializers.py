from rest_framework import serializers


class ConnectSerializer(serializers.Serializer):
    access_key_id = serializers.RegexField(
        r"^[A-Z0-9]{16,128}$",
        error_messages={"invalid": "Access key IDs are 16 to 128 uppercase letters and digits."},
    )
    # Whitespace is trimmed (DRF default): a stray space from copy-paste is the usual cause of
    # signature errors.
    secret_access_key = serializers.CharField(min_length=16, max_length=256)
    bucket = serializers.RegexField(
        r"^(?!xn--)[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$",
        error_messages={
            "invalid": "Bucket names are 3 to 63 lowercase letters, digits, dots and hyphens."
        },
    )


class FileListQuerySerializer(serializers.Serializer):
    prefix = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=1024, trim_whitespace=False
    )
    page_token = serializers.CharField(required=False, default=None, max_length=2048)
