import AppKit
import SwiftUI
import Charts

struct Span: Decodable, Identifiable {let id: Int;let x0: Double;let x1: Double;let state: String}
struct Tick: Decodable, Identifiable {let id: Int;let x: Double;let label: String;let kind: String}
struct Point: Decodable, Identifiable {let id: Int;let x: Double;let y: Double}
struct Marker: Decodable, Identifiable {let id: Int;let x: Double;let label: String}
struct Lane: Decodable {let label: String;let kind: String;let maxY: Double;let spans: [Span];let ticks: [Tick];let points: [Point]}
struct Figure: Decodable {let name: String;let title: String;let subtitle: String;let note: String;let xmin: Double;let xmax: Double;let markers: [Marker];let lanes: [Lane]}

func paint(_ state: String) -> Color {
    switch state {
    case "実行中": return Color(red: 0.15, green: 0.55, blue: 0.36)
    case "実行待ち": return .orange
    case "待機": return Color(red: 0.35, green: 0.56, blue: 0.80)
    case "合成advance", "公開間隔": return Color(red: 0.45, green: 0.41, blue: 0.67)
    default: return Color(white: 0.87)
    }
}

struct Panel: View {
    let figure: Figure
    let lane: Lane
    let last: Bool
    var body: some View {
        HStack(spacing: 14) {
            Text(lane.label).font(.system(size: 13)).frame(width: 116, alignment: .leading)
            Chart {
                if lane.kind == "spans" {
                    RectangleMark(xStart: .value("時刻", figure.xmin), xEnd: .value("時刻", figure.xmax), yStart: .value("下", 0), yEnd: .value("上", 1)).foregroundStyle(paint("未観測"))
                    ForEach(lane.spans.filter {$0.x1 > figure.xmin && $0.x0 < figure.xmax}) { s in
                        RectangleMark(xStart: .value("時刻", max(figure.xmin, s.x0)), xEnd: .value("時刻", min(figure.xmax, s.x1)), yStart: .value("下", 0.12), yEnd: .value("上", 0.88)).foregroundStyle(paint(s.state))
                    }
                } else if lane.kind == "ticks" {
                    ForEach(lane.ticks.filter {$0.x >= figure.xmin && $0.x <= figure.xmax}) { t in
                        RuleMark(x: .value("時刻", t.x), yStart: .value("下", 0.05), yEnd: .value("上", t.kind == "HAL時刻" ? 0.48 : 0.95))
                            .foregroundStyle(t.kind == "HAL時刻" ? Color.orange : Color.blue)
                            .lineStyle(StrokeStyle(lineWidth: 1.5, dash: t.kind == "HAL時刻" ? [4, 3] : []))
                    }
                } else {
                    RuleMark(y: .value("下限", 0)).foregroundStyle(Color.gray.opacity(0.3))
                    RuleMark(y: .value("容量", lane.maxY)).foregroundStyle(Color.gray.opacity(0.3))
                    ForEach(lane.points.filter {$0.x >= figure.xmin && $0.x <= figure.xmax}) { p in
                        LineMark(x: .value("時刻", p.x), y: .value("FIFO", p.y)).foregroundStyle(Color.teal)
                        PointMark(x: .value("時刻", p.x), y: .value("FIFO", p.y)).foregroundStyle(Color.teal).symbolSize(14)
                    }
                }
                ForEach(figure.markers) { m in
                    RuleMark(x: .value("時刻", m.x)).foregroundStyle(Color.red.opacity(0.85)).lineStyle(StrokeStyle(lineWidth: 1.3, dash: [2, 2]))
                }
            }
            .chartXScale(domain: figure.xmin...figure.xmax)
            .chartYScale(domain: 0...lane.maxY)
            .chartYAxis(.hidden)
            .chartXAxis(last ? .automatic : .hidden)
            .chartPlotStyle { plot in plot.background(Color(white: 0.98)) }
            .frame(height: last ? 104 : 74)
        }
    }
}

struct Timeline: View {
    let figure: Figure
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(figure.title).font(.system(size: 23, weight: .semibold))
            Text(figure.subtitle).font(.system(size: 14)).foregroundStyle(.secondary)
            HStack(spacing: 16) {
                ForEach(["実行中", "実行待ち", "待機", "未観測"], id: \.self) { s in
                    HStack(spacing: 5) {Rectangle().fill(paint(s)).frame(width: 14, height: 10);Text(s).font(.system(size: 11))}
                }
                Text("青線＝実際の入口 ／ 橙破線＝host時刻 ／ 赤破線＝注目点").font(.system(size: 11))
            }
            ForEach(Array(figure.lanes.enumerated()), id: \.offset) { index, lane in
                Panel(figure: figure, lane: lane, last: index == figure.lanes.count - 1)
            }
            Text("共通Mach時刻軸：基準点からのミリ秒").font(.system(size: 12)).frame(maxWidth: .infinity, alignment: .trailing)
            Text(figure.note).font(.system(size: 12)).foregroundStyle(.secondary)
        }.padding(24).frame(width: 1200).background(Color.white)
    }
}

@MainActor func render() throws {
    let args = CommandLine.arguments
    guard args.count == 3 else {throw NSError(domain: "引数はfigures.jsonと出力先", code: 1)}
    let figures = try JSONDecoder().decode([Figure].self, from: Data(contentsOf: URL(fileURLWithPath: args[1])))
    let directory = URL(fileURLWithPath: args[2], isDirectory: true)
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    for figure in figures {
        let renderer = ImageRenderer(content: Timeline(figure: figure))
        renderer.scale = 2
        guard let image = renderer.nsImage, let tiff = image.tiffRepresentation,
              let bitmap = NSBitmapImageRep(data: tiff), let png = bitmap.representation(using: .png, properties: [:]) else {throw NSError(domain: "図を描画できません", code: 2)}
        try png.write(to: directory.appendingPathComponent(figure.name + ".png"))
        print(figure.name)
    }
}
try await render()
