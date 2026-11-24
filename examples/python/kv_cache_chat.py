"""Explicit native KV reuse. The video Demo deliberately does not use this."""
from pandora_mage_vl import DynamicCache, LanguageModel

with LanguageModel.from_pretrained('models') as model, DynamicCache() as cache:
    for question in (
        'My name is Alice and my secret word is ORCHID. Reply only ACK.',
        'What is my name? Reply only the name.',
        'What is my secret word? Reply only the word.',
    ):
        result = model.generate(
            [{'role': 'user', 'content': question}], past_key_values=cache, max_new_tokens=64, do_sample=False, repetition_penalty=1.0
        )
        print(result.text)
        if result.finish_reason != 'stop':
            break
