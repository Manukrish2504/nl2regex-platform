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


class JobSubmitSerializer(serializers.Serializer):
    file_key = serializers.CharField(max_length=1024, trim_whitespace=False)
    # One of the two. Whitespace matters in a pattern and in a replacement, so neither is trimmed.
    pattern = serializers.CharField(max_length=1000, trim_whitespace=False, required=False)
    # A plain-English request. Capped, because it is sent to a language model on the server's bill.
    prompt = serializers.CharField(min_length=3, max_length=500, required=False)
    replacement = serializers.CharField(
        max_length=1000, allow_blank=True, trim_whitespace=False, default=""
    )
    columns = serializers.ListField(
        child=serializers.CharField(max_length=300, trim_whitespace=False),
        max_length=500,
        default=list,
    )

    def validate(self, data):
        if ("pattern" in data) == ("prompt" in data):
            raise serializers.ValidationError("Give either a pattern or a prompt, not both.")
        return data


class PageQuerySerializer(serializers.Serializer):
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=200, default=50)


class PreviewQuerySerializer(serializers.Serializer):
    key = serializers.CharField(max_length=1024, trim_whitespace=False)
