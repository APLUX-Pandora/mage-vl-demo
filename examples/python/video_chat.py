"""One independent video request; no previous-window conversation is supplied."""
from pandora_mage_vl import LanguageModel

with LanguageModel.from_pretrained("models") as model:
    result = model.generate(
        [{
            "role": "user",
            "content": [
                {"type": "video", "video": "demo/samples/cafe15.mp4"},
                {"type": "text", "text": "Summarize the visible actions in this video."},
            ],
        }],
        max_new_tokens=64,
        do_sample=False,
        repetition_penalty=1.0,
        video_target_canvas=12,    # Total canvas budget for the video
        video_group_size=20,       # Candidate frames sampled per temporal group
        video_images_per_group=4,  # Canvases assembled per group
    )
    print(result.text)
