import platform
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from lexicon import Lexicon
from utils import load_corpus, write_corpus


class GizaAligner:
    def __init__(
        self,
        bin_dir: Path,
        model_dir: Path,
        m1: Optional[int] = None,
        m2: Optional[int] = None,
        mh: Optional[int] = None,
        m3: Optional[int] = None,
        m4: Optional[int] = None,
    ) -> None:
        self.bin_dir = bin_dir
        self.model_dir = model_dir
        self.m1 = m1
        self.m2 = m2
        self.mh = mh
        self.m3 = m3
        self.m4 = m4

    @property
    def file_suffix(self) -> str:
        suffix = ""
        if self.m3 is None or self.m3 > 0 or self.m4 is None or self.m4 > 0:
            suffix = "3.final"
        elif self.mh is None or self.mh > 0:
            suffix = f"hmm.{5 if self.mh is None else self.mh}"
        elif self.m2 is not None and self.m2 > 0:
            suffix = f"2.{self.m2}"
        elif self.m1 is None or self.m1 > 0:
            suffix = f"1.{5 if self.m1 is None else self.m1}"
        return suffix

    def train(self, src_file_path: Path, trg_file_path: Path) -> None:
        self.model_dir.mkdir(exist_ok=True)

        if self.m4 is None or self.m4 > 0:
            self._execute_mkcls(src_file_path)
            self._execute_mkcls(trg_file_path)

        src_trg_snt_file_path, trg_src_snt_file_path = self._execute_plain2snt(src_file_path, trg_file_path)

        self._execute_snt2cooc(src_trg_snt_file_path)
        self._execute_snt2cooc(trg_src_snt_file_path)

        src_trg_prefix = src_trg_snt_file_path.with_suffix("")
        src_trg_output_prefix = src_trg_prefix.parent / (src_trg_prefix.name + "_invswm")
        self._execute_mgiza(src_trg_snt_file_path, src_trg_output_prefix)
        src_trg_alignments_file_path = src_trg_output_prefix.with_suffix(f".A{self.file_suffix}.all")
        self._merge_alignment_parts(src_trg_output_prefix, src_trg_alignments_file_path)

        trg_src_output_prefix = src_trg_prefix.parent / (src_trg_prefix.name + "_swm")
        self._execute_mgiza(trg_src_snt_file_path, trg_src_output_prefix)
        trg_src_alignments_file_path = trg_src_output_prefix.with_suffix(f".A{self.file_suffix}.all")
        self._merge_alignment_parts(trg_src_output_prefix, trg_src_alignments_file_path)

    def align(self, out_file_path: Path, sym_heuristic: str = "grow-diag-final-and") -> None:
        src_trg_alignments_file_path = self.model_dir / f"src_trg_invswm.A{self.file_suffix}.all"
        trg_src_alignments_file_path = self.model_dir / f"src_trg_swm.A{self.file_suffix}.all"
        self._symmetrize(src_trg_alignments_file_path, trg_src_alignments_file_path, out_file_path, sym_heuristic)

    def get_direct_lexicon(self, include_special_tokens: bool = False) -> Lexicon:
        src_vocab = self._load_vocab("src")
        trg_vocab = self._load_vocab("trg")
        return self._load_lexicon(src_vocab, trg_vocab, "invswm", include_special_tokens=include_special_tokens)

    def get_inverse_lexicon(self, include_special_tokens: bool = False) -> Lexicon:
        src_vocab = self._load_vocab("src")
        trg_vocab = self._load_vocab("trg")
        return self._load_lexicon(trg_vocab, src_vocab, "swm", include_special_tokens=include_special_tokens)

    def extract_lexicon(self, out_file_path: Path) -> None:
        direct_lexicon = self.get_direct_lexicon()
        inverse_lexicon = self.get_inverse_lexicon()
        lexicon = Lexicon.symmetrize(direct_lexicon, inverse_lexicon)
        lexicon.write(out_file_path)

    def _execute_mkcls(self, input_file_path: Path) -> None:
        mkcls_path = self.bin_dir / "mkcls"
        if platform.system() == "Windows":
            mkcls_path = mkcls_path.with_suffix(".exe")
        if not mkcls_path.is_file():
            raise RuntimeError("mkcls is not installed.")

        input_prefix = input_file_path.stem
        output_file_path = self.model_dir / f"{input_prefix}.vcb.classes"

        args: List[str] = [str(mkcls_path), "-n10", f"-p{input_file_path}", f"-V{output_file_path}"]
        subprocess.run(args)

    def _execute_plain2snt(self, src_file_path: Path, trg_file_path: Path) -> Tuple[Path, Path]:
        plain2snt_path = self.bin_dir / "plain2snt"
        if platform.system() == "Windows":
            plain2snt_path = plain2snt_path.with_suffix(".exe")
        if not plain2snt_path.is_file():
            raise RuntimeError("plain2snt is not installed.")

        src_prefix = src_file_path.stem
        trg_prefix = trg_file_path.stem

        src_trg_snt_file_path = self.model_dir / f"{src_prefix}_{trg_prefix}.snt"
        trg_src_snt_file_path = self.model_dir / f"{trg_prefix}_{src_prefix}.snt"

        args: List[str] = [
            str(plain2snt_path),
            str(src_file_path),
            str(trg_file_path),
            "-vcb1",
            str(self.model_dir / f"{src_prefix}.vcb"),
            "-vcb2",
            str(self.model_dir / f"{trg_prefix}.vcb"),
            "-snt1",
            str(src_trg_snt_file_path),
            "-snt2",
            str(trg_src_snt_file_path),
        ]
        subprocess.run(args)
        return src_trg_snt_file_path, trg_src_snt_file_path

    def _execute_snt2cooc(self, snt_file_path: Path) -> None:
        snt2cooc_path = self.bin_dir / "snt2cooc"
        if platform.system() == "Windows":
            snt2cooc_path = snt2cooc_path.with_suffix(".exe")
        if not snt2cooc_path.is_file():
            raise RuntimeError("snt2cooc is not installed.")

        snt_dir = snt_file_path.parent
        prefix = snt_file_path.stem
        prefix1, prefix2 = prefix.split("_", maxsplit=2)

        args: List[str] = [
            str(snt2cooc_path),
            str(self.model_dir / f"{prefix}.cooc"),
            str(snt_dir / f"{prefix1}.vcb"),
            str(snt_dir / f"{prefix2}.vcb"),
            str(snt_file_path),
        ]
        subprocess.run(args)

    def _execute_mgiza(self, snt_file_path: Path, output_path: Path) -> None:
        mgiza_path = self.bin_dir / "mgiza"
        if platform.system() == "Windows":
            mgiza_path = mgiza_path.with_suffix(".exe")
        if not mgiza_path.is_file():
            raise RuntimeError("mgiza is not installed.")

        snt_dir = snt_file_path.parent
        prefix = snt_file_path.stem
        prefix1, prefix2 = prefix.split("_", maxsplit=2)

        args: List[str] = [
            str(mgiza_path),
            "-C",
            str(snt_file_path),
            "-CoocurrenceFile",
            str(snt_dir / f"{prefix}.cooc"),
            "-S",
            str(snt_dir / f"{prefix1}.vcb"),
            "-T",
            str(snt_dir / f"{prefix2}.vcb"),
            "-o",
            str(output_path),
        ]
        if self.m1 is not None:
            args.extend(["-m1", str(self.m1)])
        if self.m2 is not None:
            args.extend(["-m2", str(self.m2)])
        if self.mh is not None:
            args.extend(["-mh", str(self.mh)])
        if self.m3 is not None:
            args.extend(["-m3", str(self.m3)])
        if self.m4 is not None:
            args.extend(["-m4", str(self.m4)])

        if self.m3 == 0 and self.m4 == 0:
            if self.mh is None or self.mh > 0:
                args.extend(["-th", str(5 if self.mh is None else self.mh)])
            elif self.m2 is not None and self.m2 > 0:
                args.extend(["-t2", str(self.m2)])
            elif self.m1 is None or self.m1 > 0:
                args.extend(["-t1", str(5 if self.m1 is None else self.m1)])
        subprocess.run(args, stderr=subprocess.DEVNULL)

    def _merge_alignment_parts(self, model_prefix: Path, output_file_path: Path) -> None:
        alignments: List[Tuple[int, str]] = []
        for input_file_path in model_prefix.parent.glob(model_prefix.name + f".A{self.file_suffix}.part*"):
            with open(input_file_path, "r", encoding="utf-8") as in_file:
                line_index = 0
                segment_index = 0
                cur_alignment: str = ""
                for line in in_file:
                    cur_alignment += line
                    alignment_line_index = line_index % 3
                    if alignment_line_index == 0:
                        start = line.index("(")
                        end = line.index(")")
                        segment_index = int(line[start + 1 : end])
                    elif alignment_line_index == 2:
                        alignments.append((segment_index, cur_alignment.strip()))
                        cur_alignment = ""
                    line_index += 1

        write_corpus(output_file_path, map(lambda a: str(a[1]), sorted(alignments, key=lambda a: a[0])))

    def _symmetrize(
        self, direct_align_path: Path, inverse_align_path: Path, output_path: Path, sym_heuristic: str
    ) -> None:
        args: List[str] = [
            "dotnet",
            "machine",
            "symmetrize",
            str(direct_align_path),
            str(inverse_align_path),
            str(output_path),
            "-sh",
            sym_heuristic,
        ]
        subprocess.run(args, stdout=subprocess.DEVNULL)

    def _load_vocab(self, side: str) -> List[str]:
        vocab_path = self.model_dir / f"{side}.vcb"
        vocab: List[str] = ["NULL", "UNK"]
        for line in load_corpus(vocab_path):
            index_str, word, _ = line.split()
            assert int(index_str) == len(vocab)
            vocab.append(word)
        return vocab

    def _load_lexicon(
        self, src_vocab: List[str], trg_vocab: List[str], align_model: str, include_special_tokens: bool
    ) -> Lexicon:
        lexicon = Lexicon()
        model_path = self.model_dir / f"src_trg_{align_model}.t{self.file_suffix}"
        for line in load_corpus(model_path):
            src_index_str, trg_index_str, prob_str = line.split(maxsplit=3)
            src_index = int(src_index_str)
            trg_index = int(trg_index_str)
            if include_special_tokens or (src_index > 1 and trg_index > 1):
                src_word = src_vocab[src_index]
                trg_word = trg_vocab[trg_index]
                prob = float(prob_str)
                lexicon[src_word, trg_word] = prob
        return lexicon


class Ibm1GizaAligner(GizaAligner):
    def __init__(self, bin_dir: Path, model_dir: Path) -> None:
        super().__init__(bin_dir, model_dir, mh=0, m3=0, m4=0)


class Ibm2GizaAligner(GizaAligner):
    def __init__(self, bin_dir: Path, model_dir: Path) -> None:
        super().__init__(bin_dir, model_dir, m2=5, mh=0, m3=0, m4=0)


class HmmGizaAligner(GizaAligner):
    def __init__(self, bin_dir: Path, model_dir: Path) -> None:
        super().__init__(bin_dir, model_dir, m3=0, m4=0)


class Ibm3GizaAligner(GizaAligner):
    def __init__(self, bin_dir: Path, model_dir: Path) -> None:
        super().__init__(bin_dir, model_dir, m4=0)


class Ibm4GizaAligner(GizaAligner):
    def __init__(self, bin_dir: Path, model_dir: Path) -> None:
        super().__init__(bin_dir, model_dir)
