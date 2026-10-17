"""専用Torch環境で実行する歌声F0ワーカー。音源は外部へ送信しない。"""
import argparse
import json
from pathlib import Path

import librosa
import numpy as np
import torch
import torchcrepe


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('audio', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    print('CREPE: 音源を読み込みます', flush=True)
    torch.set_num_threads(2)
    samples, sr = librosa.load(args.audio, sr=16000, mono=True)
    step, chunk = 160, 16000 * 10
    all_pitch, all_confidence = [], []
    # 文脈を付けた分割でViterbi推定。端の重複フレームは保存しない。
    for offset in range(0, len(samples), chunk):
        first, last = max(0, offset - 1600), min(len(samples), offset + chunk + 1600)
        block = torch.from_numpy(samples[first:last]).unsqueeze(0)
        # 分離後のごく小さい漏れだけの区間で推論しない。無声の音高を生成しない。
        if float(torch.sqrt(torch.mean(block ** 2))) < .001 and float(block.abs().max()) < .01:
            count = len(np.arange(offset, min(offset + chunk, len(samples)), step))
            all_pitch.extend([440.] * count)
            all_confidence.extend([0.] * count)
            print(f'CREPE: silent {min(offset + chunk, len(samples)) / sr:.1f}s', flush=True)
            continue
        with torch.inference_mode():
            pitch, confidence = torchcrepe.predict(block, sr, step, 65, 1047, 'full',
                                                   batch_size=32, device='cpu', return_periodicity=True)
            confidence = torchcrepe.filter.median(confidence, 3)
            rms = librosa.feature.rms(y=samples[first:last], frame_length=1024, hop_length=step, pad_mode='constant')[0]
            confidence[0, torch.from_numpy(rms < .0015)] = 0
            pitch = torchcrepe.filter.mean(pitch, 3)
        times = first + np.arange(pitch.shape[-1]) * step
        keep = (times >= offset) & (times < min(offset + chunk, len(samples)))
        all_pitch.extend(pitch[0].cpu().numpy()[keep].tolist())
        all_confidence.extend(confidence[0].cpu().numpy()[keep].tolist())
        print(f'CREPE: {min(offset + chunk, len(samples)) / sr:.1f}/{len(samples) / sr:.1f} seconds', flush=True)
    args.output.write_text(json.dumps({'step': step / sr, 'duration': len(samples) / sr,
                                      'f0': all_pitch, 'confidence': all_confidence}, allow_nan=False))


if __name__ == '__main__':
    main()
