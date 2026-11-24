"""One independent text request through the installed LM SDK."""
from pandora_mage_vl import LanguageModel

with LanguageModel.from_pretrained('models') as model:
    result = model.generate([{'role': 'user', 'content': 'Briefly explain what video understanding means.'}], max_new_tokens=64, do_sample=False, repetition_penalty=1.0)
    print(result.text)
