import json


class JSONSerializer:
    """Serializer for Django's Redis cache, set through OPTIONS["serializer"] in settings.

    Django's default pickles values, and unpickling bytes read from Redis would turn write access
    to Redis into code execution in the web and worker processes.
    """

    def dumps(self, obj):
        # Integers stay raw so Redis INCR/DECR keep working, as in Django's own serializer.
        if type(obj) is int:
            return obj
        return json.dumps(obj).encode()

    def loads(self, data):
        return json.loads(data)
