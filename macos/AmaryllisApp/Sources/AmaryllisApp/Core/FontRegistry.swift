import AppKit
import CoreText
import Foundation

enum AmaryllisFontRegistry {
    static let preferredPostScriptName = "Mx437_OlivettiThin_9x14"

    private static var didRegister = false
    private static let bundledFileNames: [String] = [
        "Mx437_OlivettiThin_9x14.ttf",
        "Ac437_OlivettiThin_9x14.ttf",
        "Px437_OlivettiThin_9x14.ttf",
    ]

    static func registerBundledFonts() {
        guard !didRegister else { return }
        didRegister = true

        for url in discoverBundledFontURLs() {
            CTFontManagerRegisterFontsForURL(url as CFURL, .process, nil)
        }
    }

    static func resolvedFontName() -> String {
        let candidates = [
            preferredPostScriptName,
            "Mx437_OlivettiThin_9x14",
            "Ac437_OlivettiThin_9x14",
            "Px437_OlivettiThin_9x14",
            "Mx437 OlivettiThin 9x14",
            "Ac437 OlivettiThin 9x14",
            "Px437 OlivettiThin 9x14",
            "Px437_OlivettiThin_9x14",
        ]

        for candidate in candidates where NSFont(name: candidate, size: 12) != nil {
            return candidate
        }
        return "Menlo"
    }

    private static func discoverBundledFontURLs() -> [URL] {
        let bundles = discoverCandidateBundles()

        var found: [URL] = []
        var seen: Set<String> = []
        let fileManager = FileManager.default
        for fileName in bundledFileNames {
            let nsName = fileName as NSString
            let stem = nsName.deletingPathExtension
            let ext = nsName.pathExtension

            for bundle in bundles {
                let candidates = [
                    bundle.url(forResource: stem, withExtension: ext, subdirectory: "Fonts"),
                    bundle.url(forResource: stem, withExtension: ext, subdirectory: "Resources/Fonts"),
                    bundle.url(forResource: stem, withExtension: ext),
                    bundle.bundleURL.appendingPathComponent(fileName),
                    bundle.bundleURL.appendingPathComponent("Resources", isDirectory: true).appendingPathComponent(fileName),
                    bundle.bundleURL.appendingPathComponent("Resources", isDirectory: true).appendingPathComponent("Fonts", isDirectory: true).appendingPathComponent(fileName),
                ]
                for maybeURL in candidates {
                    guard let url = maybeURL else { continue }
                    guard fileManager.fileExists(atPath: url.path) else { continue }
                    let normalized = url.standardizedFileURL.path
                    guard seen.insert(normalized).inserted else { continue }
                    found.append(url)
                }
            }
        }
        return found
    }

    private static func discoverCandidateBundles() -> [Bundle] {
        var bundles: [Bundle] = []
        var seenPaths: Set<String> = []
        let fileManager = FileManager.default

        func appendBundle(_ bundle: Bundle) {
            let normalized = bundle.bundleURL.standardizedFileURL.path
            guard seenPaths.insert(normalized).inserted else { return }
            bundles.append(bundle)
        }

        func appendBundles(in directory: URL?) {
            guard let directory else { return }
            guard let entries = try? fileManager.contentsOfDirectory(
                at: directory,
                includingPropertiesForKeys: nil,
                options: [.skipsHiddenFiles]
            ) else {
                return
            }
            for entry in entries where entry.pathExtension == "bundle" {
                guard let bundle = Bundle(url: entry) else { continue }
                appendBundle(bundle)
            }
        }

        appendBundle(Bundle.main)
        appendBundles(in: Bundle.main.resourceURL)
        if let executableURL = Bundle.main.executableURL {
            let executableDir = executableURL.deletingLastPathComponent()
            appendBundles(in: executableDir)
            appendBundles(in: executableDir.deletingLastPathComponent())
        }

        return bundles
    }
}
