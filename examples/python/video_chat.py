"""One independent video request; no previous-window conversation is supplied."""
from pandora_mage_vl import LanguageModel

with LanguageModel.from_pretrained('models') as model:
    answer = model.generate([{'role': 'user', 'content': [
        {'type': 'video', 'video': 'demo/samples/cafe15.mp4'},
        {'type': 'text', 'text': 'Summarize the visible actions in this video.'},
    ]}], max_new_tokens=64, do_sample=False, repetition_penalty=1.0)
    print(answer.text)
