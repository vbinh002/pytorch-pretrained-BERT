# coding=utf-8
# Copyright 2018 The Google AI Language Team Authors and The HugginFace Inc. team.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Tokenization classes."""

from __future__ import absolute_import, division, print_function

import collections
import logging
import os
import re
import unicodedata
from glob import glob

import sentencepiece as spm

from .file_utils import cached_path

logger = logging.getLogger(__name__)

PRETRAINED_VOCAB_ARCHIVE_MAP = {
    "bert-base-uncased": "https://s3.amazonaws.com/models.huggingface.co/bert/bert-base-uncased-vocab.txt",
    "bert-large-uncased": "https://s3.amazonaws.com/models.huggingface.co/bert/bert-large-uncased-vocab.txt",
    "bert-base-cased": "https://s3.amazonaws.com/models.huggingface.co/bert/bert-base-cased-vocab.txt",
    "bert-large-cased": "https://s3.amazonaws.com/models.huggingface.co/bert/bert-large-cased-vocab.txt",
    "bert-base-multilingual-uncased": "https://s3.amazonaws.com/models.huggingface.co/bert/bert-base-multilingual-uncased-vocab.txt",
    "bert-base-multilingual-cased": "https://s3.amazonaws.com/models.huggingface.co/bert/bert-base-multilingual-cased-vocab.txt",
    "bert-base-chinese": "https://s3.amazonaws.com/models.huggingface.co/bert/bert-base-chinese-vocab.txt",
}
PRETRAINED_VOCAB_POSITIONAL_EMBEDDINGS_SIZE_MAP = {
    "bert-base-uncased": 512,
    "bert-large-uncased": 512,
    "bert-base-cased": 512,
    "bert-large-cased": 512,
    "bert-base-multilingual-uncased": 512,
    "bert-base-multilingual-cased": 512,
    "bert-base-chinese": 512,
}
VOCAB_NAME = "vocab.txt"


def load_vocab(vocab_file):
    """Loads a vocabulary file into a dictionary."""
    vocab = collections.OrderedDict()
    index = 0
    with open(vocab_file, "r", encoding="utf-8") as reader:
        while True:
            token = reader.readline()
            if not token:
                break
            token = token.strip()
            vocab[token] = index
            index += 1
    return vocab


def whitespace_tokenize(text):
    """Runs basic whitespace cleaning and splitting on a peice of text."""
    text = text.strip()
    if not text:
        return []
    tokens = text.split()
    return tokens


class BertTokenizer(object):
    """Runs end-to-end tokenization: punctuation splitting + wordpiece"""

    def __init__(
        self,
        vocab_file=None,
        do_lower_case=True,
        max_len=512,
        never_split=("[UNK]", "[SEP]", "[PAD]", "[CLS]", "[MASK]"),
        sentencepiece=None,
    ):
        self.basic_tokenizer = BasicTokenizer(
            do_lower_case=do_lower_case, never_split=never_split
        )
        self.max_len = max_len if max_len is not None else int(1e12)

        self.sentencepiece = sentencepiece

        if not self.sentencepiece:
            assert os.path.isfile(
                vocab_file
            ), f"Can't find a vocabulary file at path '{vocab_file}'. "
            "To load the vocabulary from a Google pretrained model use "
            "`tokenizer = BertTokenizer.from_pretrained(PRETRAINED_MODEL_NAME)`"

            self.vocab = load_vocab(vocab_file)
            self.ids_to_tokens = collections.OrderedDict(
                [(ids, tok) for tok, ids in self.vocab.items()]
            )
            self.wordpiece_tokenizer = WordpieceTokenizer(vocab=self.vocab)

    def tokenize(self, text):
        split_tokens = []
        for token in self.basic_tokenizer.tokenize(text):
            if self.sentencepiece:
                for sub_token in self.sentencepiece.encode_as_pieces(token):
                    split_tokens.append(sub_token)
            else:
                for sub_token in self.wordpiece_tokenizer.tokenize(token):
                    split_tokens.append(sub_token)
        return split_tokens

    def convert_tokens_to_ids(self, tokens):
        """Converts a sequence of tokens into ids using the vocab."""
        ids = []
        for token in tokens:
            if self.sentencepiece:
                ids.append(self.sentencepiece.piece_to_id(token))
            else:
                ids.append(self.vocab[token])

        if len(ids) > self.max_len:
            raise ValueError(
                "Token indices sequence length is longer than the specified maximum "
                " sequence length for this BERT model ({} > {}). Running this"
                " sequence through BERT will result in indexing errors".format(
                    len(ids), self.max_len
                )
            )
        return ids

    def convert_ids_to_tokens(self, ids):
        """Converts a sequence of ids in wordpiece tokens using the vocab."""
        tokens = []
        for i in ids:
            if self.sentencepiece:
                tokens.append(self.sentencepiece.id_to_piece(i))
            else:
                tokens.append(self.ids_to_tokens[i])
        return tokens

    @classmethod
    def from_pretrained(
        cls, pretrained_model_name, cache_dir=None, *inputs, **kwargs
    ):
        """
        Instantiate a PreTrainedBertModel from a pre-trained model file.
        Download and cache the pre-trained model file if needed.
        """
        if pretrained_model_name in PRETRAINED_VOCAB_ARCHIVE_MAP:
            vocab_file = PRETRAINED_VOCAB_ARCHIVE_MAP[pretrained_model_name]
        else:
            vocab_file = pretrained_model_name
        if os.path.isdir(vocab_file):
            vocab_file = os.path.join(vocab_file, VOCAB_NAME)
        # redirect to the cache, if necessary
        try:
            resolved_vocab_file = cached_path(vocab_file, cache_dir=cache_dir)
        except FileNotFoundError:
            logger.error(
                "Model name '{}' was not found in model name list ({}). "
                "We assumed '{}' was a path or url but couldn't find any file "
                "associated to this path or url.".format(
                    pretrained_model_name,
                    ", ".join(PRETRAINED_VOCAB_ARCHIVE_MAP.keys()),
                    vocab_file,
                )
            )
            return None
        if resolved_vocab_file == vocab_file:
            logger.info("loading vocabulary file {}".format(vocab_file))
        else:
            logger.info(
                "loading vocabulary file {} from cache at {}".format(
                    vocab_file, resolved_vocab_file
                )
            )
        if (
            pretrained_model_name
            in PRETRAINED_VOCAB_POSITIONAL_EMBEDDINGS_SIZE_MAP
        ):
            # if we're using a pretrained model, ensure the tokenizer wont index sequences longer
            # than the number of positional embeddings
            max_len = PRETRAINED_VOCAB_POSITIONAL_EMBEDDINGS_SIZE_MAP[
                pretrained_model_name
            ]
            kwargs["max_len"] = min(kwargs.get("max_len", int(1e12)), max_len)
        # Instantiate tokenizer.
        tokenizer = cls(resolved_vocab_file, *inputs, **kwargs)
        return tokenizer


class BasicTokenizer(object):
    """Runs basic tokenization (punctuation splitting, lower casing, etc.)."""

    def __init__(
        self,
        do_lower_case=True,
        never_split=("[UNK]", "[SEP]", "[PAD]", "[CLS]", "[MASK]"),
    ):
        """Constructs a BasicTokenizer.

        Args:
          do_lower_case: Whether to lower case the input.
        """
        self.do_lower_case = do_lower_case
        self.never_split = never_split

    def tokenize(self, text):
        """Tokenizes a piece of text."""
        text = self._clean_text(text)
        # This was added on November 1st, 2018 for the multilingual and Chinese
        # models. This is also applied to the English models now, but it doesn't
        # matter since the English models were not trained on any Chinese data
        # and generally don't have any Chinese data in them (there are Chinese
        # characters in the vocabulary because Wikipedia does have some Chinese
        # words in the English Wikipedia.).
        text = self._tokenize_chinese_chars(text)
        orig_tokens = whitespace_tokenize(text)
        split_tokens = []
        for token in orig_tokens:
            if self.do_lower_case and token not in self.never_split:
                token = token.lower()
                token = self._run_strip_accents(token)
            split_tokens.extend(self._run_split_on_punc(token))

        output_tokens = whitespace_tokenize(" ".join(split_tokens))
        return output_tokens

    def _run_strip_accents(self, text):
        """Strips accents from a piece of text."""
        text = unicodedata.normalize("NFD", text)
        output = []
        for char in text:
            cat = unicodedata.category(char)
            if cat == "Mn":
                continue
            output.append(char)
        return "".join(output)

    def _run_split_on_punc(self, text):
        """Splits punctuation on a piece of text."""
        if text in self.never_split:
            return [text]
        chars = list(text)
        i = 0
        start_new_word = True
        output = []
        while i < len(chars):
            char = chars[i]
            if _is_punctuation(char):
                output.append([char])
                start_new_word = True
            else:
                if start_new_word:
                    output.append([])
                start_new_word = False
                output[-1].append(char)
            i += 1

        return ["".join(x) for x in output]

    def _tokenize_chinese_chars(self, text):
        """Adds whitespace around any CJK character."""
        output = []
        for char in text:
            cp = ord(char)
            if self._is_chinese_char(cp):
                output.append(" ")
                output.append(char)
                output.append(" ")
            else:
                output.append(char)
        return "".join(output)

    def _is_chinese_char(self, cp):
        """Checks whether CP is the codepoint of a CJK character."""
        # This defines a "chinese character" as anything in the CJK Unicode block:
        #   https://en.wikipedia.org/wiki/CJK_Unified_Ideographs_(Unicode_block)
        #
        # Note that the CJK Unicode block is NOT all Japanese and Korean characters,
        # despite its name. The modern Korean Hangul alphabet is a different block,
        # as is Japanese Hiragana and Katakana. Those alphabets are used to write
        # space-separated words, so they are not treated specially and handled
        # like the all of the other languages.
        if (
            (cp >= 0x4E00 and cp <= 0x9FFF)
            or (cp >= 0x3400 and cp <= 0x4DBF)  #
            or (cp >= 0x20000 and cp <= 0x2A6DF)  #
            or (cp >= 0x2A700 and cp <= 0x2B73F)  #
            or (cp >= 0x2B740 and cp <= 0x2B81F)  #
            or (cp >= 0x2B820 and cp <= 0x2CEAF)  #
            or (cp >= 0xF900 and cp <= 0xFAFF)
            or (cp >= 0x2F800 and cp <= 0x2FA1F)  #
        ):  #
            return True

        return False

    def _clean_text(self, text):
        """Performs invalid character removal and whitespace cleanup on text."""
        output = []
        for char in text:
            cp = ord(char)
            if cp == 0 or cp == 0xFFFD or _is_control(char):
                continue
            if _is_whitespace(char):
                output.append(" ")
            else:
                output.append(char)
        return "".join(output)


class WordpieceTokenizer(object):
    """Runs WordPiece tokenization."""

    def __init__(self, vocab, unk_token="[UNK]", max_input_chars_per_word=100):
        self.vocab = vocab
        self.unk_token = unk_token
        self.max_input_chars_per_word = max_input_chars_per_word

    def tokenize(self, text):
        """Tokenizes a piece of text into its word pieces.

        This uses a greedy longest-match-first algorithm to perform tokenization
        using the given vocabulary.

        For example:
          input = "unaffable"
          output = ["un", "##aff", "##able"]

        Args:
          text: A single token or whitespace separated tokens. This should have
            already been passed through `BasicTokenizer`.

        Returns:
          A list of wordpiece tokens.
        """

        output_tokens = []
        for token in whitespace_tokenize(text):
            chars = list(token)
            if len(chars) > self.max_input_chars_per_word:
                output_tokens.append(self.unk_token)
                continue

            is_bad = False
            start = 0
            sub_tokens = []
            while start < len(chars):
                end = len(chars)
                cur_substr = None
                while start < end:
                    substr = "".join(chars[start:end])
                    if start > 0:
                        substr = "##" + substr
                    if substr in self.vocab:
                        cur_substr = substr
                        break
                    end -= 1
                if cur_substr is None:
                    is_bad = True
                    break
                sub_tokens.append(cur_substr)
                start = end

            if is_bad:
                output_tokens.append(self.unk_token)
            else:
                output_tokens.extend(sub_tokens)
        return output_tokens


def _is_whitespace(char):
    """Checks whether `chars` is a whitespace character."""
    # \t, \n, and \r are technically contorl characters but we treat them
    # as whitespace since they are generally considered as such.
    if char == " " or char == "\t" or char == "\n" or char == "\r":
        return True
    cat = unicodedata.category(char)
    if cat == "Zs":
        return True
    return False


def _is_control(char):
    """Checks whether `chars` is a control character."""
    # These are technically control characters but we count them as whitespace
    # characters.
    if char == "\t" or char == "\n" or char == "\r":
        return False
    cat = unicodedata.category(char)
    if cat.startswith("C"):
        return True
    return False


def _is_punctuation(char):
    """Checks whether `chars` is a punctuation character."""
    cp = ord(char)
    # We treat all non-letter/number ASCII as punctuation.
    # Characters such as "^", "$", and "`" are not in the Unicode
    # Punctuation class but we treat them as punctuation anyways, for
    # consistency.
    if (
        (cp >= 33 and cp <= 47)
        or (cp >= 58 and cp <= 64)
        or (cp >= 91 and cp <= 96)
        or (cp >= 123 and cp <= 126)
    ):
        return True
    cat = unicodedata.category(char)
    if cat.startswith("P"):
        return True
    return False


class SentencePieceTokenizer(object):
    def __init__(
        self,
        model_file,
        do_lower_case=False,
        wordpiece_mode=False,
        unk_token="[unk]",
    ):
        assert os.path.isfile(model_file), "Model file not found."

        self.spm = spm.SentencePieceProcessor()
        self.spm.load(model_file)

        self.do_lower_case = do_lower_case
        self.wordpiece_mode = wordpiece_mode

        self.unk_token = unk_token
        self.unk_token_id = self.spm.PieceToId(self.unk_token)
        self.unused_token_id = self.spm.PieceToId("[unused]")

        self.wordpiece_pattern = re.compile(
            r"\S*" + re.escape(self.unk_token) + r"\S*"
        )

    def __correct_unk_id(self, _id):
        if _id == self.unused_token_id:
            return self.unk_token_id
        return _id

    def encode_as_pieces(self, sentence):
        return self.spm.EncodeAsPieces(
            self.decode_ids(self.encode_as_ids(sentence))
        )

    def encode_as_ids(self, sentence):
        if self.do_lower_case:
            sentence = sentence.lower()
        return self.spm.EncodeAsIds(
            self.decode_ids(self.spm.EncodeAsIds(sentence))
        )

    def decode_pieces(self, pieces):
        return self.decode_ids(map(self.piece_to_id, pieces))

    def decode_ids(self, ids):
        sentence = self.spm.DecodeIds(list(map(self.__correct_unk_id, ids)))
        if self.wordpiece_mode:
            return self.wordpiece_pattern.sub(self.unk_token, sentence)
        return sentence

    def id_to_piece(self, _id):
        return self.spm.IdToPiece(self.__correct_unk_id(_id))

    def piece_to_id(self, piece):
        if self.do_lower_case:
            piece = piece.lower()
        return self.__correct_unk_id(self.spm.PieceToId(piece))

    def __sizeof__(self):
        return self.spm.GetPieceSize()


if __name__ == "__main__":
    # Train SentencePiece
    corpus_file_or_dir = (
        "/media/files/dnanhkhoa/projects/workspace/corpora/pubmed_baseline.txt"
    )
    model_file = "pubmed_baseline"
    vocab_size = 32000
    # * https://github.com/google/sentencepiece/issues/9#issuecomment-289352218
    input_sentence_size = 9_000_000
    character_coverage = 1.0

    model_method = "unigram"

    unk_token = "[unk]"
    user_defined_tokens = ",".join(
        [unk_token, "[pad]", "[sep]", "[cls]", "[mask]"]
    )  # ! Should be in lowercase

    corpus_files = None
    if os.path.isfile(corpus_file_or_dir):
        corpus_files = [corpus_file_or_dir]
    elif os.path.isdir(corpus_file_or_dir):
        corpus_files = glob(
            os.path.join(corpus_file_or_dir, "**/*.*"), recursive=True
        )

    assert corpus_files, "Corpora not found."

    corpus_file = ",".join(corpus_files)

    spm.SentencePieceTrainer.Train(
        f"--input={corpus_file} --model_prefix={model_file} "
        f"--vocab_size={vocab_size} --character_coverage={character_coverage} "
        f"--model_type={model_method} "
        f"--bos_id=-1 --eos_id=-1 --pad_id=-1 "
        f"--unk_id=0 --unk_piece=[unused] --unk_surface={unk_token} "
        f"--user_defined_symbols={user_defined_tokens} "
        f"--input_sentence_size={input_sentence_size}"
    )
