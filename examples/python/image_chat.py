"""Single-image LM request. Edit the local paths and question as needed."""
from pandora_mage_vl import LanguageModel

with LanguageModel.from_pretrained('models') as model:
    answer = model.generate([{'role': 'user', 'content': [
        {'type': 'image', 'image': 'demo/samples/cafe-frame.png'},
        {'type': 'text', 'text': 'Describe the visible people and their actions.'},
    ]}], max_new_tokens=64, do_sample=False, repetition_penalty=1.0)
    print(answer.text)
