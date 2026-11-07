#include "llama.h"
#include "ggml-backend.h"

#include <algorithm>
#include <cstring>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <regex>
#include <stdexcept>
#include <string>
#include <vector>

struct capture_data {
    std::filesystem::path directory;
    std::regex filter;
    std::ofstream manifest;
    int step = 0;
    int index = 0;
};

static void write_floats(const std::filesystem::path & path, const float * data, size_t count) {
    std::ofstream out(path, std::ios::binary);
    out.exceptions(std::ios::failbit | std::ios::badbit);
    out.write(reinterpret_cast<const char *>(data), count * sizeof(float));
}

static bool capture(ggml_tensor * t, bool ask, void * opaque) {
    auto & data = *static_cast<capture_data *>(opaque);
    if (ask) {
        return std::regex_match(t->name, data.filter);
    }
    if (t->type != GGML_TYPE_F32) {
        throw std::runtime_error(std::string("selected tensor is not F32: ") + t->name);
    }
    std::vector<uint8_t> raw(ggml_nbytes(t));
    ggml_backend_tensor_get(t, raw.data(), 0, raw.size());
    std::vector<float> values;
    values.reserve(ggml_nelements(t));
    for (int64_t i3 = 0; i3 < t->ne[3]; ++i3)
        for (int64_t i2 = 0; i2 < t->ne[2]; ++i2)
            for (int64_t i1 = 0; i1 < t->ne[1]; ++i1)
                for (int64_t i0 = 0; i0 < t->ne[0]; ++i0) {
                    float value;
                    std::memcpy(&value, raw.data() + i0*t->nb[0] + i1*t->nb[1] + i2*t->nb[2] + i3*t->nb[3], sizeof(value));
                    values.push_back(value);
                }
    const std::string file = std::to_string(data.step) + "-" + std::to_string(data.index++) + ".f32";
    write_floats(data.directory / file, values.data(), values.size());
    data.manifest << data.step << '\t' << t->name << '\t' << ggml_op_name(t->op) << '\t'
                  << ggml_backend_buffer_name(t->buffer) << '\t';
    for (int i = 0; i < 4; ++i) data.manifest << t->ne[i] << (i == 3 ? '\t' : ',');
    data.manifest << file << '\n';
    data.manifest.flush();
    return true;
}

int main(int argc, char ** argv) {
    if (argc != 7) {
        std::cerr << "usage: probe model.gguf cpu|HRX0 output-dir tensor-regex|- prompt decode-token-id\n";
        return 2;
    }
    try {
        std::filesystem::create_directories(argv[3]);
        capture_data data{argv[3], std::regex(argv[4]), std::ofstream(std::filesystem::path(argv[3]) / "tensors.tsv")};
        data.manifest.exceptions(std::ios::failbit | std::ios::badbit);
        ggml_backend_load_all();
        llama_backend_init();
        const bool cpu = std::string(argv[2]) == "cpu";
        ggml_backend_dev_t devices[] = {nullptr, nullptr};
        if (!cpu) {
            devices[0] = ggml_backend_dev_by_name(argv[2]);
            if (!devices[0]) throw std::runtime_error("requested backend device is unavailable");
        }
        auto mp = llama_model_default_params();
        mp.devices = devices;
        mp.n_gpu_layers = cpu ? 0 : 99;
        mp.load_mtp = false;
        auto * model = llama_model_load_from_file(argv[1], mp);
        if (!model) throw std::runtime_error("model load failed");
        auto cp = llama_context_default_params();
        cp.n_ctx = 512;
        cp.n_batch = 512;
        cp.n_ubatch = 512;
        cp.n_seq_max = 1;
        cp.n_threads = cp.n_threads_batch = 8;
        cp.type_k = cp.type_v = GGML_TYPE_F16;
        cp.flash_attn_type = LLAMA_FLASH_ATTN_TYPE_ENABLED;
        cp.offload_kqv = cp.op_offload = !cpu;
        cp.kv_unified = false;
        if (std::string(argv[4]) != "-") {
            cp.cb_eval = capture;
            cp.cb_eval_user_data = &data;
        }
        auto * ctx = llama_init_from_model(model, cp);
        if (!ctx) throw std::runtime_error("context creation failed");
        const auto * vocab = llama_model_get_vocab(model);
        const std::string prompt = argv[5];
        std::vector<llama_token> tokens(prompt.size() + 32);
        int count = llama_tokenize(vocab, prompt.data(), static_cast<int>(prompt.size()), tokens.data(),
                                   static_cast<int>(tokens.size()), true, true);
        if (count < 0) {
            tokens.resize(-count);
            count = llama_tokenize(vocab, prompt.data(), static_cast<int>(prompt.size()), tokens.data(),
                                   static_cast<int>(tokens.size()), true, true);
        }
        if (count <= 0) throw std::runtime_error("tokenization failed");
        tokens.resize(count);
        std::ofstream token_file(data.directory / "tokens.txt");
        for (auto token : tokens) token_file << token << '\n';
        const auto decode_token = static_cast<llama_token>(std::stoi(argv[6]));
        token_file << decode_token << '\n';
        const char * chunk_env = std::getenv("HRX_PROBE_CHUNK_SIZE");
        const int chunk_size = chunk_env ? std::stoi(chunk_env) : count;
        if (chunk_size <= 0) throw std::runtime_error("chunk size must be positive");
        for (data.step = 0; data.step < 2; ++data.step) {
            data.index = 0;
            std::vector<llama_token> input = data.step == 0 ? tokens : std::vector<llama_token>{decode_token};
            for (size_t offset = 0; offset < input.size(); offset += chunk_size) {
                const auto length = static_cast<int32_t>(std::min(input.size() - offset, static_cast<size_t>(chunk_size)));
                if (llama_decode(ctx, llama_batch_get_one(input.data() + offset, length)))
                    throw std::runtime_error("decode failed");
            }
            const float * logits = llama_get_logits_ith(ctx, -1);
            const int n_vocab = llama_vocab_n_tokens(vocab);
            write_floats(data.directory / (std::to_string(data.step) + "-logits.f32"), logits, n_vocab);
            const auto top = std::max_element(logits, logits + n_vocab) - logits;
            std::cout << "step=" << data.step << " top_token=" << top << " logit=" << logits[top] << '\n';
            std::cout.flush();
        }
        llama_free(ctx);
        llama_model_free(model);
        llama_backend_free();
        return 0;
    } catch (const std::exception & error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
