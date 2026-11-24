/* Explicit native KV reuse through the public C ABI. */
#include "mage_vl.h"
#include <stdio.h>
#include <string.h>

static int turn(mage_vl_engine *model, uint64_t cache, const char *request) {
    int rc = mage_vl_configure_cached_request(model, cache, request);
    if (rc < 0) return rc;
    rc = mage_vl_start_text(model);
    if (rc < 0) return rc;
    int finished = 0;
    while (!finished) {
        rc = mage_vl_next(model);
        if (rc < 0 && rc != MAGE_VL_ERR_WOULD_BLOCK) return rc;
        for (;;) {
            uint8_t text[4096];
            mage_vl_text_info info = {0}; info.struct_size = sizeof(info);
            int count = mage_vl_read_text(model, text, sizeof(text), &info);
            if (count < 0) return count;
            if (!count) break;
            fwrite(text, 1, (size_t)count, stdout);
        }
        for (;;) {
            mage_vl_event event = {0}; event.struct_size = sizeof(event);
            rc = mage_vl_read_event(model, &event);
            if (rc < 0) return rc;
            if (!rc) break;
            if (event.type == MAGE_VL_EVENT_SUMMARY_FINISHED) {
                if (event.stop_reason != MAGE_VL_STOP_EOS) return MAGE_VL_ERR_STATE;
                finished = 1;
            }
        }
    }
    putchar('\n');
    mage_vl_cache_info info = {0}; info.struct_size = sizeof(info);
    rc = mage_vl_cache_get_info(model, cache, &info);
    if (rc < 0) return rc;
    printf("KV: turn=%llu retained=%llu reused=%llu actual=%llu\n",
           (unsigned long long)info.turns, (unsigned long long)info.cached_tokens,
           (unsigned long long)info.reused_tokens, (unsigned long long)info.backend_tokens);
    return info.valid && info.cached_tokens == info.backend_tokens ? 0 : MAGE_VL_ERR_STATE;
}

int main(int argc, char **argv) {
    const char *directory = argc > 1 ? argv[1] : "models";
    const char *requests[] = {
        "{\"input_kind\":\"text\",\"messages\":[{\"role\":\"user\",\"content\":\"My name is Alice and my secret word is ORCHID. Reply only ACK.\"}],\"max_new_tokens\":64,\"do_sample\":false,\"repetition_penalty\":1.0}",
        "{\"input_kind\":\"text\",\"messages\":[{\"role\":\"user\",\"content\":\"What is my name? Reply only the name.\"}],\"max_new_tokens\":64,\"do_sample\":false,\"repetition_penalty\":1.0}",
        "{\"input_kind\":\"text\",\"messages\":[{\"role\":\"user\",\"content\":\"What is my secret word? Reply only the word.\"}],\"max_new_tokens\":64,\"do_sample\":false,\"repetition_penalty\":1.0}"
    };
    mage_vl_engine *model = NULL;
    mage_vl_options options;
    uint64_t cache = 0;
    int rc = mage_vl_default_options(&options);
    if (rc == 0) {
        model = mage_vl_create(directory, &options);
        if (!model) rc = mage_vl_create_status();
    }
    if (rc == 0) rc = mage_vl_cache_begin(model, &cache);
    for (size_t index = 0; rc == 0 && index < sizeof(requests)/sizeof(requests[0]); ++index)
        rc = turn(model, cache, requests[index]);
    if (rc < 0) fprintf(stderr, "SDK failure %d: %s\n", rc,
                        model ? mage_vl_last_error(model) : mage_vl_create_error());
    if (cache) {
        if (rc < 0) mage_vl_reset(model);
        int cleanup = mage_vl_cache_release(model, cache);
        if (rc == 0) rc = cleanup;
    }
    if (model) { int cleanup = mage_vl_destroy_owned(&model); if (rc == 0) rc = cleanup; }
    return rc == 0 ? 0 : 1;
}
