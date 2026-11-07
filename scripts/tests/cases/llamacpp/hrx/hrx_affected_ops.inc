struct test_iq_residual : public test_mul_mat {
    test_iq_residual(ggml_type type) : test_mul_mat(type, GGML_TYPE_F32, 5120, 1, 17408, {1,1}, {1,1}) {}
    bool run_whole_graph() override { return true; }
    std::string op_desc(ggml_tensor*) override { return "MUL_MAT_RESIDUAL"; }
    ggml_tensor* build_graph(ggml_context* ctx) override {
        ggml_tensor* projection = test_mul_mat::build_graph(ctx);
        ggml_tensor* residual = ggml_new_tensor_2d(ctx, GGML_TYPE_F32, 5120, 1);
        return ggml_add(ctx, projection, residual);
    }
};
static std::vector<std::unique_ptr<test_case>> make_test_cases_eval() {
    std::vector<std::unique_ptr<test_case>> test_cases;
    for (auto type : {GGML_TYPE_IQ2_S, GGML_TYPE_IQ3_S}) {
        test_cases.emplace_back(new test_mul_mat(type, GGML_TYPE_F32, 5120, 1, 17408, {1,1}, {1,1}));
        test_cases.emplace_back(new test_iq_residual(type));
        test_cases.emplace_back(new test_mul_mat_vec_fusion(type, GGML_GLU_OP_SWIGLU, 1, 17408, 5120,
            false, 1, 1, false, false, true, false, {1,1}));
    }
    return test_cases;
}
