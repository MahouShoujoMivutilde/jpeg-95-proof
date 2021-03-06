from PIL import Image
from multiprocessing import Pool, freeze_support
from functools import partial
from os import listdir, path, makedirs
import matplotlib.pyplot as plt
from shutil import rmtree
from time import clock
from datetime import timedelta
from sys import argv
import argparse 
import subprocess 
import re

supported = ['.jpg', '.jpeg', '.gif', '.png', '.webp', '.tif']

def get_args():
    parser = argparse.ArgumentParser(description = "Строит график зависимости объективного качества (PSNR/SSIM) и размера файла от % качества jpeg, требует matplotlib, Pillow и опционально psutil, а также ffmpeg 3.x в PATH")
    parser.add_argument("-s", default = False, action = "store_true", help = "Не удалять папку с полученными jpeg")
    parser.add_argument("-p", default = False, action = "store_true", help = "Подписать соответствующие розовым линиям отметки на OY")
    requiredNamed = parser.add_argument_group("required named arguments")
    requiredNamed.add_argument("-i", required = True, help = "Путь к исходному изображению / к папке с исходными изображениями (для расчета усредненного графика)")
    return parser.parse_args()

def to_jpeg(q, base_path, dst):
    with Image.open(base_path) as base:
        base.convert('RGB').save(r'{}\{}.jpeg'.format(dst, q), quality = q)

def get_imgs(folder, fmt = ''):
    return [path.abspath(path.join(folder, i)) for i in listdir(folder) if ('.{}'.format(fmt) in i and path.splitext(i)[1] in supported)]

# https://github.com/MahouShoujoMivutilde/compare_images
def compare_images(ref_img, cmp_img, method):
    p = subprocess.Popen(['ffmpeg.exe', '-loglevel', 'error', '-i', ref_img, '-i', cmp_img, '-filter_complex', '{}=stats_file=-'.format(method), '-f', 'null', '-'], stdout = subprocess.PIPE, stderr = subprocess.PIPE)
    outs, _ = p.communicate()
    p.wait()
    if re.match("ssim", method, re.IGNORECASE):
        return float(re.search(r'\bAll:(\d+(?:\.\d+)?)\s', outs.decode('utf-8')).group(0)[4:])
    elif re.match("psnr", method, re.IGNORECASE):
        return float(re.search(r'\bpsnr_avg:[-+]?[0-9]*\.?[0-9]+', outs.decode('utf-8')).group(0)[9:])
    else:
        raise Exception('RegExp to match "{}" value not implemented yet, sorry...'.format(method))

def draw2(ox, oy, fp, name, test_method, new_alg, format_quality):
    # TODO: сделать адекватный (не всегда 24) вывод значений oy
    def extract_x(lst):
        return list(zip(*lst))[0]
    
    def extract_y(lst):
        return list(zip(*lst))[1]
    
    def filter(ox, oy):
        fuchsia = []
        k = []
        for x, y in zip(ox, oy):
            if x % 5 == 0:
                fuchsia.append((x, y))
            else:
                k.append((x, y))
        return(fuchsia, k)
    
    plt.subplots(figsize = (10, 10))
    plt.plot(ox, oy, 'ro', markersize = 2)
    f, k = filter(ox, oy)
    plt.vlines(extract_x(k), [0], extract_y(k), lw = 0.5)
    plt.vlines(extract_x(f), [0], extract_y(f), lw = 0.5, color = 'fuchsia')
    plt.xticks(range(min(ox) - 1, max(ox) + 1, 5))
    plt.yticks(extract_y(f) if new_alg else [round(min(oy) + i*(max(oy) - min(oy))/24, 4) for i in range(0, 24)] + [max(oy)])
    quality_step = sorted(ox)[1] - sorted(ox)[0] 
    plt.axis([min(ox) - quality_step, max(ox) + quality_step, min(oy), max(oy)])
    plt.xlabel(format_quality)
    plt.ylabel(test_method)
    plt.tight_layout()
    plt.savefig(path.join(fp, '{} - {} graph.png'.format(name, test_method)), dpi = 200)

def lower_child_priority():
    try:
        from psutil import Process, BELOW_NORMAL_PRIORITY_CLASS
        parent = Process()
        parent.nice(BELOW_NORMAL_PRIORITY_CLASS)
        for child in parent.children():
            child.nice(BELOW_NORMAL_PRIORITY_CLASS)
    except:
        pass

def process(base_path, store, quality_range = range(1, 101)):
    folder = path.splitext(base_path)[0]
    try:
        makedirs(folder)
    except FileExistsError:
        pass
    try:
        print('  генерируем jpeg...')
        with Pool() as pool:
            lower_child_priority()
            pool.map(partial(to_jpeg, base_path = base_path, dst = folder), quality_range)
        jpegs = get_imgs(folder, 'jpeg')

        print('  рассчитываем SSIM...')
        with Pool() as pool:
            lower_child_priority()
            SSIMs = pool.map(partial(compare_images, cmp_img = base_path, method = 'ssim'), jpegs)

        print('  рассчитываем PSNR...')
        with Pool() as pool:
            lower_child_priority()
            PSNRs = pool.map(partial(compare_images, cmp_img = base_path, method = 'psnr'), jpegs)

        ox = [int(path.split(i)[1].split('.')[0]) for i in jpegs] # нужно чтобы сохранить порядок соотношения xi к yi
        sizes = [path.getsize(i)/1024 for i in jpegs]
    except Exception as e:
        print('  файл пропущен: {}'.format(e))

    if not store:
        try:
            rmtree(folder)
        except:
            pass

    try:
        assert len(ox) == len(SSIMs) == len(PSNRs) == len(sizes)
        quality = {lvl: {'SSIM': ssim, 'PSNR': psnr, 'size': size} for lvl, ssim, psnr, size in zip(ox, SSIMs, PSNRs, sizes)}
        assert quality != {}
        return {'folder': folder, 'quality': quality}
    except:
        pass

def get_avg(atype, stats):
    ox = []
    oy = []
    for k, _ in stats[0]['quality'].items():
        arr = [s['quality'][k][atype] for s in stats]
        ox.append(k)
        oy.append(sum(arr)/len(arr))
    return(ox, oy)

if __name__ == '__main__':
    freeze_support()
    args = get_args()
    source_imgs = []
    if path.isdir(args.i):
        source_imgs = get_imgs(args.i)
    elif path.isfile(args.i):
        source_imgs.append(path.abspath(args.i))
    else:
        raise Exception('{} не папка и не файл!\nЖизнь меня к такому не готовила!'.format(args.i))
    
    start = clock()
    stats = []
    for count, img in enumerate(source_imgs):
        if len(source_imgs) > 1:
            print('{} из {}: {}'.format(count + 1, len(source_imgs), path.split(img)[1]))
 
        res = process(img, args.s)
        if res:
            stats.append(res)
 
        if len(source_imgs) > 1:
            print('\n')

    ox1, SSIMs = get_avg('SSIM', stats)
    ox2, PSNRs = get_avg('PSNR', stats)
    ox3, sizes = get_avg('size', stats)

    graph_dst, name = path.split(path.abspath(args.i))
    if not path.isdir(args.i):
        name = path.splitext(name)[0]

    print('\n  рисуем графики...\n')

    draw2(ox1, SSIMs, graph_dst, name, 'SSIM', args.p, 'jpeg качество, %')
    draw2(ox2, PSNRs, graph_dst, name, 'PSNR', args.p, 'jpeg качество, %')
    draw2(ox3, sizes, graph_dst, name, 'размер, kb', args.p, 'jpeg качество, %')

    print('%s: %s\n' % (path.split(argv[0])[1], str(timedelta(seconds = round(clock() - start)))))