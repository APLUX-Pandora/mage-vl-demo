/* RGB8 input is 512x288, interleaved and already resized by the caller. */
#include "mage_vl.h"
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv) {
    if (argc != 3) {fprintf(stderr, "Usage: image_chat MODEL_ROOT RGB8_FILE\n"); return 2;}
    int rc = 0;
    FILE *input = fopen(argv[2], "rb");
    if (!input) {
        perror(argv[2]);
        return 1;
    }
    unsigned char *rgb = malloc(512u * 288u * 3u);
    if (!rgb) {
        fclose(input);
        return 1;
    }
    size_t bytes = fread(rgb, 1, 512u * 288u * 3u, input);
    int extra = fgetc(input); fclose(input);
    if (bytes != 512u * 288u * 3u || extra != EOF) {free(rgb); return 2;}
    mage_vl_engine *model = NULL;
    mage_vl_options options;
    rc = mage_vl_default_options(&options);
    if (rc != 0) goto cleanup;
    model = mage_vl_create(argv[1], &options);
    if (!model) rc = mage_vl_create_status();
    if (rc != 0) {fprintf(stderr, "%s\n", mage_vl_create_error()); goto cleanup;}
    rc = mage_vl_configure_request(model, "{\"messages\":[{\"role\":\"user\",\"content\":\"Describe the image.\"}],\"max_new_tokens\":16,\"do_sample\":false,\"repetition_penalty\":1.0}");
    if (rc == 0) rc = mage_vl_start_image_rgb(model, rgb, bytes);
    for (unsigned step = 0; rc == 0 && step < 1000; ++step) {
        int next = mage_vl_next(model);
        if (next < 0) {rc = next; break;}
        unsigned char text[4096]; mage_vl_text_info info = {0}; info.struct_size = sizeof(info);
        int n;
        while ((n = mage_vl_read_text(model, text, sizeof(text), &info)) > 0) fwrite(text, 1, (size_t)n, stdout);
        if (n < 0) {rc = n; break;}
        mage_vl_event event = {0}; event.struct_size = sizeof(event);
        int event_status;
        while ((event_status = mage_vl_read_event(model, &event)) > 0) {
            if (event.type == MAGE_VL_EVENT_SUMMARY_FINISHED) {putchar('\n'); goto cleanup;}
        }
        if (event_status < 0) {rc = event_status; break;}
        if (step == 999) rc = MAGE_VL_ERR_STATE;
    }
    if (rc < 0) fprintf(stderr, "%s\n", mage_vl_last_error(model));
cleanup:
    if (model) {int close_rc = mage_vl_destroy_owned(&model); if (rc == 0) rc = close_rc;}
    free(rgb);
    return rc < 0 ? 1 : 0;
}
