/**
 * Lucid Dreaming - Interactive 3D UI Kernel
 * Phase 13 Principle 5: GRooT-Dreams style interactive visualization
 */
#ifndef LUCID_DREAMING_CU
#define LUCID_DREAMING_CU

#include <cuda_runtime.h>
#include <cstdint>

#define INTERACTION_NONE    0
#define INTERACTION_SELECT  1
#define INTERACTION_DRAG    2
#define INTERACTION_INJECT  3
#define INTERACTION_ERASE   4
#define INTERACTION_POLISH  5

struct LucidInteraction {
    int mode;
    float cursor_x, cursor_y, cursor_z;
    float brush_radius, brush_strength;
    int target_cell_type;
    uint32_t user_id;
    float timestamp;
};

struct MagneticPolisher {
    float oscillation_phase, oscillation_freq;
    float magnetic_strength, abrasive_intensity;
    int target_boundary_layer;
};

struct CellFeedback {
    float self_recognition, hebbian_strength, energy_level, stability;
    uint8_t is_selected, highlight_type;
};

__device__ __forceinline__ float cursor_distance(
    int cx, int cy, int cz, float x, float y, float z
) {
    float dx=(float)cx-x, dy=(float)cy-y, dz=(float)cz-z;
    return sqrtf(dx*dx+dy*dy+dz*dz);
}

__global__ void lucid_interaction_kernel(
    uint8_t* states, float* equanimity, float* energy,
    CellFeedback* feedback, LucidInteraction* interaction,
    int w, int h, int d, uint32_t timestep
) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= w*h*d) return;
    int x=idx%w, y=(idx/w)%h, z=idx/(w*h);
    float dist = cursor_distance(x,y,z, interaction->cursor_x, interaction->cursor_y, interaction->cursor_z);
    if (dist > interaction->brush_radius) { feedback[idx].is_selected = 0; return; }
    float t = dist / interaction->brush_radius;
    float influence = (1.0f-t)*(1.0f-t) * interaction->brush_strength;
    switch (interaction->mode) {
        case INTERACTION_SELECT: feedback[idx].is_selected = 1; break;
        case INTERACTION_DRAG: if (states[idx]==2||states[idx]==3) energy[idx] += influence*0.1f; break;
        case INTERACTION_INJECT: if (states[idx]==0 && influence>0.5f) { states[idx]=interaction->target_cell_type; energy[idx]=1.0f; } break;
        case INTERACTION_POLISH:
            if (feedback[idx].self_recognition < 0.5f) { equanimity[idx] += influence*0.2f; feedback[idx].highlight_type = 1; }
            else if (feedback[idx].self_recognition > 0.9f) { feedback[idx].highlight_type = 3; }
            break;
    }
}

__global__ void magnetic_polisher_kernel(
    uint8_t* states, float* equanimity, CellFeedback* feedback,
    MagneticPolisher* polisher, int w, int h, int d, uint32_t timestep, float dt
) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= w*h*d || states[idx] != 2) return;
    polisher->oscillation_phase += polisher->oscillation_freq * dt;
    float osc = sinf(polisher->oscillation_phase);
    int x=idx%w, y=(idx/w)%h, z=idx/(w*h);
    int tx = w/2 + (int)(osc*10.0f);
    float dist = sqrtf((float)((x-tx)*(x-tx) + (y-h/2)*(y-h/2) + (z-d/2)*(z-d/2)));
    float err = dist / (float)w;
    equanimity[idx] += polisher->abrasive_intensity * err * osc;
    if (equanimity[idx] < 0.0f) equanimity[idx] = 0.0f;
    if (equanimity[idx] > 1.0f) equanimity[idx] = 1.0f;
    feedback[idx].stability = 1.0f - err;
    if (err < 0.1f) feedback[idx].self_recognition = fminf(1.0f, feedback[idx].self_recognition + 0.01f);
}

#endif
