"""The test classes the suite runs, in the order it reports them.

The registry is explicit because the suite's scope walks a static import graph: a class imported by
name at run time would be invisible to it, so every module is imported here instead. `GROUPS` is what
the runner counts against and what the selector picks from.
"""

import unittest

from scripts.tests.cases.asr.llamacpp.test_gemma_audio import GemmaAudioTests
from scripts.tests.cases.asr.llamacpp.test_qwen_asr_profiles import QwenAsrProfiles
from scripts.tests.cases.asr.shared.test_delivery import DeliveryTests
from scripts.tests.cases.asr.shared.test_file_profiles import FileProfiles
from scripts.tests.cases.asr.shared.test_practice import PracticeTests
from scripts.tests.cases.asr.shared.test_startup_contracts import StartupContracts
from scripts.tests.cases.asr.shared.test_streaming_adapters import StreamingAdapters
from scripts.tests.cases.asr.shared.test_vad_turns import VadTurns
from scripts.tests.cases.asr.shared.test_whisper_compare import WhisperCompareTests
from scripts.tests.cases.asr.test_whisper_profiles import WhisperProfiles
from scripts.tests.cases.audiocpp.audio_comparison import AudioComparison
from scripts.tests.cases.audiocpp.test_audiocpp_transport import TransportBenchmark
from scripts.tests.cases.audiocpp.test_tts_profiles import TtsProfiles
from scripts.tests.cases.coding_agents.pi.test_pi_packages import PiPackageTests
from scripts.tests.cases.coding_agents.shared.framework_clients import FrameworkClients
from scripts.tests.cases.coding_agents.shared.test_benchmark_backends import BenchmarkBackendsTests
from scripts.tests.cases.coding_agents.shared.test_benchmark_matrix import BenchmarkMatrixTests
from scripts.tests.cases.coding_agents.shared.test_benchmark_requests import BenchmarkRequestsTests
from scripts.tests.cases.koboldcpp.kobold_lite_streaming import StreamingPatch
from scripts.tests.cases.koboldcpp.test_external_bridge import ExternalBridgeTests
from scripts.tests.cases.koboldcpp.test_kobold_image_swap import SwapTests
from scripts.tests.cases.koboldcpp.test_kobold_lite_patch import ExternalSeedTests
from scripts.tests.cases.koboldcpp.test_kobold_options import KoboldOptionTests
from scripts.tests.cases.koboldcpp.test_kobold_stack_vram import StackProbeTests
from scripts.tests.cases.llamacpp.hrx.test_hrx_build import HrxBuildTests
from scripts.tests.cases.llamacpp.test_ngram import NgramWorkloads
from scripts.tests.cases.llamacpp.test_speech_ui import SpeechUiTests
from scripts.tests.cases.personal.comfyui.test_comfyui_video import ExecutionTests, WorkflowTests
from scripts.tests.cases.personal.comfyui.test_ltx_prompt_cache import PromptCacheTests
from scripts.tests.cases.personal.comfyui.test_verify_node import ProviderTests, VerifyNodeTests
from scripts.tests.cases.review.checks.test_annotations import DefaultTests, FindingsTests, ScoreTests
from scripts.tests.cases.review.checks.test_bare_any import BareAnyTests
from scripts.tests.cases.review.checks.test_comments import CommentPolicyTests
from scripts.tests.cases.review.checks.test_dead_code import FindingTests, ScopedSkipTests
from scripts.tests.cases.review.checks.test_docs import (
    GeneratedPageTests,
    LinkTests,
    MarkdownNameTests,
    ModelNameTests,
    PointerTests,
    RoleTests,
    RootDocumentTests,
)
from scripts.tests.cases.review.checks.test_duplicates import DuplicateReportTests
from scripts.tests.cases.review.checks.test_dynamic_imports import DynamicImportTests
from scripts.tests.cases.review.checks.test_folder_rule import FolderRuleTests
from scripts.tests.cases.review.checks.test_layout import PolicyTests
from scripts.tests.cases.review.checks.test_line_length import LimitsReportTests, LineLengthTests
from scripts.tests.cases.review.checks.test_network_timeouts import NetworkTimeoutTests
from scripts.tests.cases.review.checks.test_overlay_access import OverlayAccessTests
from scripts.tests.cases.review.checks.test_owned_tokens import OwnedTokenTests
from scripts.tests.cases.review.checks.test_similarity import (
    SimilarityCodeTests,
    SimilarityFindingTests,
    SimilarityNeighborTests,
    SimilaritySourceTests,
    SimilarityUnitTests,
)
from scripts.tests.cases.review.checks.test_spellings import AmericanSpellingTests
from scripts.tests.cases.review.checks.test_typography import CheckTests, ScanTests, SuffixTests
from scripts.tests.cases.review.checks.test_walrus import WalrusTests
from scripts.tests.cases.review.test_examples import ExamplesPageTests
from scripts.tests.cases.review.test_public_audit import PublicAuditTests
from scripts.tests.cases.review.test_review_gate import GateScopeTests
from scripts.tests.cases.shared.benchmarks.test_benchmark_lifecycle import BenchmarkLifecycleTests
from scripts.tests.cases.shared.benchmarks.test_benchmark_vram import BenchmarkVramTests
from scripts.tests.cases.shared.benchmarks.test_coding_engines import CodingEngineSummaryTests
from scripts.tests.cases.shared.benchmarks.test_context_stream import ContextStreamTests
from scripts.tests.cases.shared.benchmarks.test_framework_compare import (
    AlternateArmTests,
    KoboldArmTests,
    LemonadeModelTests,
    RecognitionLegTests,
    SpeechLegTests,
    SpeechPlausibilityTests,
    StreamChatTests,
    SummaryTests,
)
from scripts.tests.cases.shared.benchmarks.test_language_corpus import CorpusManifestTests, ExtractionTests
from scripts.tests.cases.shared.benchmarks.test_probe_runner import ProbeRunnerTests
from scripts.tests.cases.shared.benchmarks.test_provenance import (
    BinaryTests,
    BlockTests,
    CorpusTests,
    FileIdentityTests,
    ProducerTests,
    WorkspaceTests,
)
from scripts.tests.cases.shared.gate.test_bat_launchers import BatLaunchers
from scripts.tests.cases.shared.gate.test_consent import ConsentTests
from scripts.tests.cases.shared.gate.test_inference_engines import InferenceEngines
from scripts.tests.cases.shared.gate.test_label_vocabulary import LabelVocabularyTests
from scripts.tests.cases.shared.gate.test_live_stamp import LiveStampTests
from scripts.tests.cases.shared.gate.test_model_run import ModelRunTests
from scripts.tests.cases.shared.gate.test_scoped_selection import TestSelection
from scripts.tests.cases.shared.gate.test_validate import ValidatePlanTests
from scripts.tests.cases.shared.models.test_model_analysis import ModelAnalysisTests
from scripts.tests.cases.shared.models.test_model_catalog import ModelCatalogTests
from scripts.tests.cases.shared.models.test_model_languages import ModelLanguages
from scripts.tests.cases.shared.models.test_model_sync import ModelSyncTests
from scripts.tests.cases.shared.models.test_model_updates import (
    CatalogOverlayTests,
    DownloadModelsTests,
    ModelUpdatesTests,
    TransferTests,
    UpdateModelsTests,
)
from scripts.tests.cases.shared.regression.test_boundaries import TestBoundaries
from scripts.tests.cases.shared.regression.test_regression_fixtures import RegressionFixtures
from scripts.tests.cases.shared.reports.test_reporting import Reporting
from scripts.tests.cases.shared.reports.test_reports import ReportOutputs
from scripts.tests.cases.shared.runtime.test_backend_sessions import BackendSessions
from scripts.tests.cases.shared.runtime.test_gpu_memory_monitor import MemoryMonitorTests
from scripts.tests.cases.shared.runtime.test_image_on_demand import NativePassthroughTests, ResidencyTests
from scripts.tests.cases.shared.runtime.test_resources import ResourceTests
from scripts.tests.cases.shared.runtime.test_shared_runtime import (
    ExitReportTests,
    OwnedLaunchTests,
    ReadinessRouteTests,
    SharedRuntimeTests,
    SweepMessageTests,
)
from scripts.tests.cases.shared.tools.test_capability_matrix import FreshnessTests, HeadlineTests, RenderTests
from scripts.tests.cases.shared.tools.test_language_matrix import LanguageMatrixTests
from scripts.tests.cases.shared.tools.test_local_overlay import LocalOverlayTests
from scripts.tests.cases.shared.tools.test_low_integrity import LowIntegrityTests
from scripts.tests.cases.shared.tools.test_model_admin import ModelAdminTests
from scripts.tests.cases.shared.tools.test_preflight import PreflightTests
from scripts.tests.cases.shared.tools.test_refresh_index import (
    RefreshBackgroundTests,
    RefreshLockTests,
    RefreshPlanTests,
    RefreshReportTests,
)
from scripts.tests.cases.shared.tools.test_rename_path import (
    CollapseTests,
    ImportRewriteTests,
    MoveParsingTests,
    PreviewTests,
    ReferenceRewriteTests,
    ScanScopeTests,
)
from scripts.tests.cases.shared.tools.test_rocm_inventory import RocmInventoryTests
from scripts.tests.cases.shared.tools.test_sample_code import SampleCodeTests
from scripts.tests.cases.shared.tools.test_stage_runner import StageRunnerTests
from scripts.tests.cases.shared.tools.test_state_cleanup import StateCleanupTests
from scripts.tests.cases.shared.tools.test_strata_profile import StrataProfileLinkTests
from scripts.tests.cases.shared.tools.test_toolchains import ToolchainTests
from scripts.tests.cases.shared.tools.test_yaml_table import YamlTableTests
from scripts.tests.cases.shared.workflows.test_config_sync import ConfigSyncTests
from scripts.tests.cases.shared.workflows.test_speech_profiles import SpeechProfiles
from scripts.tests.cases.shared.workflows.test_text_processing import TextProcessingTests
from scripts.tests.cases.shared.workflows.test_workflow_defaults import WorkflowDefaultsTests
from scripts.tests.cases.strata.test_strata_pi import StrataPiTests
from scripts.tests.cases.strata.test_strata_profiles import StrataProfileTests
from scripts.tests.cases.suites import frameworks_smoke
from scripts.tests.cases.suites.framework_updates import FrameworkUpdates
from scripts.tests.cases.suites.framework_updates_sources import FrameworkUpdateSources
from scripts.tests.cases.suites.shared_contracts import SharedContracts
from scripts.tests.cases.test_lemonade_launcher import LemonadeLauncherTests, LemonadeOwnedStartTests

# The registry the runner counts and the selector picks from.
GROUPS: tuple[type[unittest.TestCase], ...] = (
    BenchmarkLifecycleTests,
    BenchmarkVramTests,
    StreamChatTests,
    SpeechLegTests,
    RecognitionLegTests,
    SummaryTests,
    LemonadeModelTests,
    AlternateArmTests,
    KoboldArmTests,
    SpeechPlausibilityTests,
    CorpusManifestTests,
    ExtractionTests,
    WorkspaceTests,
    FileIdentityTests,
    CorpusTests,
    BlockTests,
    ProducerTests,
    BinaryTests,
    FreshnessTests,
    HeadlineTests,
    RenderTests,
    CheckTests,
    ScanTests,
    SuffixTests,
    FindingTests,
    ExternalSeedTests,
    GeneratedPageTests,
    MarkdownNameTests,
    ModelNameTests,
    LinkTests,
    PointerTests,
    RoleTests,
    RootDocumentTests,
    SharedRuntimeTests,
    ReadinessRouteTests,
    OwnedLaunchTests,
    SweepMessageTests,
    StartupContracts,
    RegressionFixtures,
    TestBoundaries,
    VadTurns,
    PracticeTests,
    DeliveryTests,
    StreamingAdapters,
    ModelLanguages,
    ModelAnalysisTests,
    TextProcessingTests,
    BatLaunchers,
    InferenceEngines,
    ModelAdminTests,
    LowIntegrityTests,
    ConsentTests,
    GateScopeTests,
    CommentPolicyTests,
    FindingsTests,
    ScoreTests,
    DefaultTests,
    NetworkTimeoutTests,
    SimilarityUnitTests,
    SimilarityNeighborTests,
    SimilarityFindingTests,
    SimilaritySourceTests,
    SimilarityCodeTests,
    AmericanSpellingTests,
    StrataProfileLinkTests,
    AudioComparison,
    WorkflowTests,
    ExecutionTests,
    VerifyNodeTests,
    ProviderTests,
    PromptCacheTests,
    TtsProfiles,
    FrameworkClients,
    BenchmarkBackendsTests,
    BenchmarkMatrixTests,
    BenchmarkRequestsTests,
    StrataPiTests,
    StrataProfileTests,
    PiPackageTests,
    ConfigSyncTests,
    ModelCatalogTests,
    CatalogOverlayTests,
    ModelUpdatesTests,
    UpdateModelsTests,
    TransferTests,
    DownloadModelsTests,
    LocalOverlayTests,
    SampleCodeTests,
    LabelVocabularyTests,
    YamlTableTests,
    PolicyTests,
    BareAnyTests,
    LineLengthTests,
    LimitsReportTests,
    LiveStampTests,
    LanguageMatrixTests,
    RocmInventoryTests,
    StageRunnerTests,
    StateCleanupTests,
    MoveParsingTests,
    ImportRewriteTests,
    PreviewTests,
    CollapseTests,
    ReferenceRewriteTests,
    RefreshBackgroundTests,
    RefreshLockTests,
    RefreshPlanTests,
    RefreshReportTests,
    ScanScopeTests,
    ProbeRunnerTests,
    ModelRunTests,
    ToolchainTests,
    ValidatePlanTests,
    PreflightTests,
    PublicAuditTests,
    OverlayAccessTests,
    OwnedTokenTests,
    DuplicateReportTests,
    DynamicImportTests,
    ScopedSkipTests,
    WalrusTests,
    ExamplesPageTests,
    FolderRuleTests,
    SpeechProfiles,
    WorkflowDefaultsTests,
    WhisperCompareTests,
    FileProfiles,
    WhisperProfiles,
    QwenAsrProfiles,
    GemmaAudioTests,
    ModelSyncTests,
    CodingEngineSummaryTests,
    ContextStreamTests,
    FrameworkUpdates,
    FrameworkUpdateSources,
    ReportOutputs,
    NgramWorkloads,
    SpeechUiTests,
    LemonadeLauncherTests,
    LemonadeOwnedStartTests,
    Reporting,
    ResourceTests,
    MemoryMonitorTests,
    HrxBuildTests,
    NativePassthroughTests,
    ResidencyTests,
    SharedContracts,
    StreamingPatch,
    ExternalBridgeTests,
    KoboldOptionTests,
    SwapTests,
    StackProbeTests,
    TransportBenchmark,
    BackendSessions,
    TestSelection,
    ExitReportTests,
    # - the launcher and proxy block is scoped like everything else: a change to that wiring keeps it,
    #   a change elsewhere leaves it to the push, so no class sits outside the graph
    *frameworks_smoke.DEFAULT_GROUPS,
)
