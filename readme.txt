行人流量统计系统
================

一、开发环境
------------
操作系统：Windows
开发语言：Python 3.11
主要依赖：
1. PyQt6 6.7.1
2. OpenCV 4.11.0.86
3. Ultralytics 8.4.41
4. PyTorch 2.3.0 + CUDA 12.1
5. torchvision 0.18.0 + CUDA 12.1
6. deep-sort-realtime 1.3.2
7. matplotlib 3.10.9
8. numpy 1.26.4

二、部署环境
------------
1. Windows 10/11 64 位系统
2. Python 3.11
3. 建议使用带 NVIDIA 显卡的电脑运行；本项目依赖文件中使用的是 CUDA 12.1 版本的 PyTorch，适合有兼容驱动的 NVIDIA 显卡环境
4. 需要先安装 requirements.txt 中的依赖
5. 运行方式：
   （1）进入项目目录
   （2）安装依赖：pip install -r requirements.txt
   （3）启动程序：python run.py

三、包内文件说明
----------------
1. run.py
   程序启动入口。

2. requirements.txt
   项目运行依赖列表。

3. app/
   应用主流程代码。
   - config.py：默认参数配置
   - main.py：主窗口、播放控制、检测调度、回放逻辑

4. core/
   核心算法代码。
   - detection.py：行人检测
   - tracking.py：目标跟踪
   - counting.py：区域人数与通过统计
   - types.py：数据结构定义
   - exceptions.py：异常定义

5. services/
   服务层代码。
   - detection_worker.py：后台检测线程
   - recorder.py：处理后视频写入

6. storage/
   数据存储代码。
   - sqlite_store.py：SQLite 数据库读写

7. ui/
   界面代码。
   - main_view.py：界面布局
   - video_label.py：视频显示与 ROI 区域交互

8. models/
   YOLO 模型文件。
   - yolo11n.pt
   - yolo11s.pt
   - yolo11m.pt

9. input/
   默认输入视频目录。可将待检测视频放入此处，也可在程序中手动选择其他位置的视频。

10. data/
    运行后自动保存统计数据库的目录。

11. output/
    运行后自动保存带检测标注输出视频的目录。
