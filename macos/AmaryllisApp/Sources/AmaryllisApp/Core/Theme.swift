import SwiftUI

enum AmaryllisTheme {
    static let background = Color(red: 0.02, green: 0.025, blue: 0.022)
    static let backgroundMid = Color(red: 0.035, green: 0.04, blue: 0.036)
    static let surface = Color(red: 0.07, green: 0.08, blue: 0.074)
    static let surfaceAlt = Color(red: 0.10, green: 0.112, blue: 0.102)
    static let border = Color(red: 0.27, green: 0.31, blue: 0.28)
    static let borderSoft = Color(red: 0.17, green: 0.20, blue: 0.18)
    static let accent = Color(red: 0.74, green: 0.11, blue: 0.13)
    static let accentSoft = Color(red: 0.25, green: 0.07, blue: 0.08)
    static let phosphor = Color(red: 0.76, green: 0.86, blue: 0.73)
    static let phosphorDim = Color(red: 0.54, green: 0.62, blue: 0.52)
    static let amber = Color(red: 0.88, green: 0.72, blue: 0.46)
    static let textPrimary = phosphor
    static let textSecondary = phosphorDim
    static let inputBackground = Color(red: 0.04, green: 0.05, blue: 0.045)
    static let inputBorder = Color(red: 0.33, green: 0.40, blue: 0.34)
    static let okGreen = Color(red: 0.42, green: 0.86, blue: 0.54)

    private static let terminalFontName: String = AmaryllisFontRegistry.resolvedFontName()

    static func titleFont(size: CGFloat = 24) -> Font {
        pixelFont(size: size)
    }

    static func sectionFont(size: CGFloat = 17) -> Font {
        pixelFont(size: size)
    }

    static func bodyFont(size: CGFloat = 13, weight: Font.Weight = .regular) -> Font {
        _ = weight
        return pixelFont(size: size)
    }

    static func monoFont(size: CGFloat = 11, weight: Font.Weight = .regular) -> Font {
        _ = weight
        return pixelFont(size: size)
    }

    private static func pixelFont(size: CGFloat) -> Font {
        Font.custom(terminalFontName, size: snappedPixelSize(size))
    }

    private static func snappedPixelSize(_ value: CGFloat) -> CGFloat {
        let allowed: [CGFloat] = [9, 10, 12, 14, 16, 18, 20, 24, 28, 32]
        let clamped = max(9, min(32, value))
        var nearest = allowed[0]
        var nearestDistance = abs(allowed[0] - clamped)
        for candidate in allowed.dropFirst() {
            let distance = abs(candidate - clamped)
            if distance < nearestDistance {
                nearest = candidate
                nearestDistance = distance
            }
        }
        return nearest
    }
}

struct AmaryllisTerminalBackground: View {
    var body: some View {
        ZStack {
            LinearGradient(
                colors: [AmaryllisTheme.background, AmaryllisTheme.backgroundMid, AmaryllisTheme.background],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
            .ignoresSafeArea()

            Rectangle()
                .fill(
                    LinearGradient(
                        stops: [
                            .init(color: Color.black.opacity(0.18), location: 0.0),
                            .init(color: Color.clear, location: 0.08),
                            .init(color: Color.black.opacity(0.16), location: 0.16),
                            .init(color: Color.clear, location: 0.24),
                            .init(color: Color.black.opacity(0.14), location: 0.32),
                            .init(color: Color.clear, location: 0.40),
                            .init(color: Color.black.opacity(0.12), location: 0.48),
                            .init(color: Color.clear, location: 0.56),
                            .init(color: Color.black.opacity(0.10), location: 0.64),
                            .init(color: Color.clear, location: 0.72),
                            .init(color: Color.black.opacity(0.08), location: 0.80),
                            .init(color: Color.clear, location: 0.88),
                            .init(color: Color.black.opacity(0.06), location: 0.96),
                        ],
                        startPoint: .top,
                        endPoint: .bottom
                    )
                )
                .ignoresSafeArea()
                .allowsHitTesting(false)

            Rectangle()
                .fill(
                    RadialGradient(
                        colors: [Color.white.opacity(0.03), Color.clear],
                        center: .center,
                        startRadius: 60,
                        endRadius: 720
                    )
                )
                .ignoresSafeArea()
                .blendMode(.screen)
                .allowsHitTesting(false)
        }
    }
}

struct AmaryllisPrimaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(AmaryllisTheme.bodyFont(size: 13, weight: .semibold))
            .foregroundStyle(AmaryllisTheme.phosphor.opacity(configuration.isPressed ? 0.82 : 1.0))
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
            .background(
                RoundedRectangle(cornerRadius: 3)
                    .fill(configuration.isPressed ? AmaryllisTheme.accentSoft.opacity(0.84) : AmaryllisTheme.accentSoft)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 3)
                    .stroke(AmaryllisTheme.accent, lineWidth: 1)
            )
    }
}

struct AmaryllisSecondaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(AmaryllisTheme.bodyFont(size: 13, weight: .semibold))
            .foregroundStyle(AmaryllisTheme.textPrimary.opacity(configuration.isPressed ? 0.78 : 1.0))
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
            .background(
                RoundedRectangle(cornerRadius: 3)
                    .fill(configuration.isPressed ? AmaryllisTheme.surface : AmaryllisTheme.surfaceAlt)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 3)
                    .stroke(AmaryllisTheme.border.opacity(0.9), lineWidth: 1)
            )
    }
}

struct AmaryllisTerminalTextFieldStyle: TextFieldStyle {
    func _body(configuration: TextField<Self._Label>) -> some View {
        configuration
            .font(AmaryllisTheme.bodyFont(size: 13, weight: .regular))
            .foregroundStyle(AmaryllisTheme.textPrimary)
            .padding(.horizontal, 8)
            .padding(.vertical, 6)
            .background(
                RoundedRectangle(cornerRadius: 3)
                    .fill(AmaryllisTheme.inputBackground)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 3)
                    .stroke(AmaryllisTheme.inputBorder, lineWidth: 1)
            )
    }
}

extension View {
    func amaryllisCard() -> some View {
        self
            .padding(12)
            .background(
                RoundedRectangle(cornerRadius: 6)
                    .fill(AmaryllisTheme.surface)
                    .overlay(
                        RoundedRectangle(cornerRadius: 6)
                            .stroke(AmaryllisTheme.borderSoft, lineWidth: 1)
                    )
            )
            .overlay(alignment: .topLeading) {
                Rectangle()
                    .fill(AmaryllisTheme.border.opacity(0.55))
                    .frame(height: 1)
            }
    }

    func amaryllisEditorSurface() -> some View {
        self
            .padding(6)
            .background(
                RoundedRectangle(cornerRadius: 4)
                    .fill(AmaryllisTheme.inputBackground)
                    .overlay(
                        RoundedRectangle(cornerRadius: 4)
                            .stroke(AmaryllisTheme.inputBorder, lineWidth: 1)
                    )
            )
    }
}
