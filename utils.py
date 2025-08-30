import io
import json
from PIL import Image
import zipfile
import exception

def is_emoji(character):
    if "<:" in character:
        return True

    # Get the Unicode code point of the character
    code_point = ord(character)
    # Check if the code point is in one of the emoji ranges
    return (
        code_point in range(0x1F600, 0x1F64F) or
        code_point in range(0x1F300, 0x1F5FF) or
        code_point in range(0x1F680, 0x1F6FF) or
        code_point in range(0x1F700, 0x1F77F)
    )

async def ugoria_merge(client, id) -> tuple[bytes, str]:
    ugo_resp = await client.get("https://www.pixiv.net/ajax/illust/"+id+"/ugoira_meta")
    if ugo_resp.status == 200:
        ugo_json_resp = json.loads(await ugo_resp.text())
        ugo_zip_resp = await client.get(ugo_json_resp["body"]["originalSrc"])
        if ugo_zip_resp.status == 200:
            frames = {f["file"]: f["delay"] for f in ugo_json_resp["body"]["frames"]}
            zipcontent = await ugo_zip_resp.read()
            with zipfile.ZipFile(io.BytesIO(zipcontent)) as zf:
                files = zf.namelist()
                images = []
                durations = []
                width = 0
                height = 0
                for file in files:
                    f = io.BytesIO(zf.read(file))
                    im = Image.open(fp=f)
                    width = max(im.width, width)
                    height = max(im.height, height)
                    images.append(im)
                    durations.append(int(frames[file]))

                first_im = images.pop(0)
                image = io.BytesIO()
                first_im.save(image, format='webp', save_all=True, append_images=images, duration=durations, lossless=True, quality=100)
                image = image.getvalue()
                image_name = "ugoria_"+ str(id) + ".webp"
                
                return image, image_name
        else:
            raise exception.RequestFailed("request to pixiv ugoria zip failed")
    else:
        raise exception.RequestFailed("request to pixiv ugoria api failed")