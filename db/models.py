from tortoise import fields, models

class Image(models.Model):
    id = fields.IntField(pk=True)
    phash = fields.TextField()
    dhash = fields.TextField()
    source_url = fields.TextField()  # Original URL (Pixiv, Twitter, etc.)
    source_platform = fields.CharField(max_length=32)  # "pixiv", "twitter", etc.
    guild_id = fields.BigIntField()  # Discord server ID
    thread_id = fields.BigIntField()  # Thread where first posted
    message_id = fields.BigIntField()  # Message ID of the post
    posted_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "images"