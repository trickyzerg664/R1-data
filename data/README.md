# Bundled candidate questions

`candidates.jsonl.gz` and `manifest.json` are intended to be committed with the code.
They contain real NQ and HotpotQA **training** questions and answer aliases, extracted
from the existing Search-R1 prepared data. No model-generated trajectories are bundled.

Target: 3000 **accepted** trajectories, not 3000 input questions. All remaining filtered
training candidates are kept as reserves. Generation stops at the target or candidate
exhaustion; 3000 accepted samples cannot be guaranteed if the teacher fails validation.

Filters: empty question/answer removal, question text deduplication, and exclusion of
question overlaps with the supplied evaluation parquet. Stable per-source SHA256
ordering is interleaved between NQ and HotpotQA. See manifest for counts and hashes.

Answer aliases are used only for local evaluation. Never include them in teacher
prompts or retry hints. The original prepared parquet's prompts/reward fields are
discarded during bundling. Keep this folder separate from generated output.

Prepared source: https://huggingface.co/datasets/PeterJinGo/nq_hotpotqa_train
(revision recorded in manifest). Original dataset family:
https://huggingface.co/datasets/RUC-NLPIR/FlashRAG_datasets
and https://github.com/PeterGriffinJin/Search-R1 . Underlying datasets retain their
own terms and attribution. The prepared dataset revision and input SHA256 are recorded;
the original FlashRAG revision is not assumed. Review original dataset/provider terms
before publishing a public dataset; do not assign the code license to the data.
