/* SPDX-License-Identifier: LGPL-2.1-or-later */
#ifndef MAGE_FFMPEG_H
#define MAGE_FFMPEG_H

/* Replacement ABI for the two FFmpeg shared libraries. Requires the corresponding
 * FFmpeg headers. These functions use the original FFmpeg signatures and ownership. */
#ifdef __cplusplus
extern "C" {
#endif

#include <libavcodec/avcodec.h>
#include <libswscale/swscale.h>

unsigned mage_pixel_avcodec_version(void);
const AVCodec *mage_pixel_avcodec_find_decoder(enum AVCodecID id);
AVCodecContext *mage_pixel_avcodec_alloc_context3(const AVCodec *codec);
int mage_pixel_avcodec_open2(AVCodecContext *ctx, const AVCodec *codec, AVDictionary **options);
int mage_pixel_avcodec_send_packet(AVCodecContext *ctx, const AVPacket *packet);
int mage_pixel_avcodec_receive_frame(AVCodecContext *ctx, AVFrame *frame);
void mage_pixel_avcodec_free_context(AVCodecContext **ctx);
AVPacket *mage_pixel_av_packet_alloc(void);
void mage_pixel_av_packet_free(AVPacket **packet);
int mage_pixel_av_new_packet(AVPacket *packet, int size);
void mage_pixel_av_packet_unref(AVPacket *packet);
AVFrame *mage_pixel_av_frame_alloc(void);
void mage_pixel_av_frame_free(AVFrame **frame);
void mage_pixel_av_frame_unref(AVFrame *frame);
void *mage_pixel_av_mallocz(size_t size);
struct SwsContext *mage_pixel_sws_getContext(int src_width, int src_height, enum AVPixelFormat src_format,
    int dst_width, int dst_height, enum AVPixelFormat dst_format, int flags,
    SwsFilter *src_filter, SwsFilter *dst_filter, const double *parameters);
void mage_pixel_sws_freeContext(struct SwsContext *ctx);
int mage_pixel_sws_scale(struct SwsContext *ctx, const uint8_t *const src[], const int src_stride[],
    int src_y, int src_height, uint8_t *const dst[], const int dst_stride[]);
const int *mage_pixel_sws_getCoefficients(int colorspace);
int mage_pixel_sws_setColorspaceDetails(struct SwsContext *ctx, const int inv_table[4], int src_range,
    const int table[4], int dst_range, int brightness, int contrast, int saturation);

unsigned mage_bitcost_avcodec_version(void);
const AVCodec *mage_bitcost_avcodec_find_decoder(enum AVCodecID id);
AVCodecContext *mage_bitcost_avcodec_alloc_context3(const AVCodec *codec);
int mage_bitcost_avcodec_open2(AVCodecContext *ctx, const AVCodec *codec, AVDictionary **options);
int mage_bitcost_avcodec_send_packet(AVCodecContext *ctx, const AVPacket *packet);
int mage_bitcost_avcodec_receive_frame(AVCodecContext *ctx, AVFrame *frame);
void mage_bitcost_avcodec_free_context(AVCodecContext **ctx);
AVPacket *mage_bitcost_av_packet_alloc(void);
void mage_bitcost_av_packet_free(AVPacket **packet);
int mage_bitcost_av_new_packet(AVPacket *packet, int size);
void mage_bitcost_av_packet_unref(AVPacket *packet);
AVFrame *mage_bitcost_av_frame_alloc(void);
void mage_bitcost_av_frame_free(AVFrame **frame);
void mage_bitcost_av_frame_unref(AVFrame *frame);
void *mage_bitcost_av_mallocz(size_t size);
struct SwsContext *mage_bitcost_sws_getContext(int src_width, int src_height, enum AVPixelFormat src_format,
    int dst_width, int dst_height, enum AVPixelFormat dst_format, int flags,
    SwsFilter *src_filter, SwsFilter *dst_filter, const double *parameters);
void mage_bitcost_sws_freeContext(struct SwsContext *ctx);
int mage_bitcost_sws_scale(struct SwsContext *ctx, const uint8_t *const src[], const int src_stride[],
    int src_y, int src_height, uint8_t *const dst[], const int dst_stride[]);
const int *mage_bitcost_sws_getCoefficients(int colorspace);
int mage_bitcost_sws_setColorspaceDetails(struct SwsContext *ctx, const int inv_table[4], int src_range,
    const int table[4], int dst_range, int brightness, int contrast, int saturation);

#ifdef __cplusplus
}
#endif
#endif
