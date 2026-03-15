import SwiftUI

struct ModelsView: View {
    @EnvironmentObject private var appState: AppState

    @State private var modelToDownload: String = ""
    @State private var providerForDownload: String = "mlx"
    @State private var quickSearch: String = ""
    @State private var showAdvancedModelManagement: Bool = false
    @State private var loadingModelID: String?
    @State private var downloadingModelID: String?

    private let fallbackSuggested: [String: [APIModelCatalog.SuggestedModel]] = [
        "mlx": [
            APIModelCatalog.SuggestedModel(id: "mlx-community/Qwen2.5-1.5B-Instruct-4bit", label: "Qwen 2.5 1.5B Instruct 4bit"),
            APIModelCatalog.SuggestedModel(id: "mlx-community/Qwen2.5-7B-Instruct-4bit", label: "Qwen 2.5 7B Instruct 4bit"),
            APIModelCatalog.SuggestedModel(id: "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit", label: "Qwen 2.5 Coder 7B Instruct 4bit"),
            APIModelCatalog.SuggestedModel(id: "mlx-community/Llama-3.2-3B-Instruct-4bit", label: "Llama 3.2 3B Instruct 4bit"),
            APIModelCatalog.SuggestedModel(id: "mlx-community/Llama-3.1-8B-Instruct-4bit", label: "Llama 3.1 8B Instruct 4bit"),
            APIModelCatalog.SuggestedModel(id: "mlx-community/Mistral-7B-Instruct-v0.3-4bit", label: "Mistral 7B Instruct v0.3 4bit"),
            APIModelCatalog.SuggestedModel(id: "mlx-community/Mixtral-8x7B-Instruct-v0.1-4bit", label: "Mixtral 8x7B Instruct v0.1 4bit"),
            APIModelCatalog.SuggestedModel(id: "mlx-community/Phi-3.5-mini-instruct-4bit", label: "Phi 3.5 Mini Instruct 4bit"),
            APIModelCatalog.SuggestedModel(id: "mlx-community/phi-4-4bit", label: "Phi 4 4bit"),
            APIModelCatalog.SuggestedModel(id: "mlx-community/gemma-2-9b-it-4bit", label: "Gemma 2 9B IT 4bit"),
            APIModelCatalog.SuggestedModel(id: "mlx-community/DeepSeek-R1-Distill-Qwen-7B-4bit", label: "DeepSeek R1 Distill Qwen 7B 4bit"),
            APIModelCatalog.SuggestedModel(id: "mlx-community/DeepSeek-R1-Distill-Llama-8B-4bit", label: "DeepSeek R1 Distill Llama 8B 4bit"),
        ],
        "ollama": [
            APIModelCatalog.SuggestedModel(id: "llama3.3", label: "Llama 3.3"),
            APIModelCatalog.SuggestedModel(id: "llama3.2", label: "Llama 3.2"),
            APIModelCatalog.SuggestedModel(id: "qwen2.5", label: "Qwen 2.5"),
            APIModelCatalog.SuggestedModel(id: "qwen2.5-coder", label: "Qwen 2.5 Coder"),
            APIModelCatalog.SuggestedModel(id: "mistral", label: "Mistral"),
            APIModelCatalog.SuggestedModel(id: "mixtral", label: "Mixtral"),
            APIModelCatalog.SuggestedModel(id: "phi4", label: "Phi 4"),
            APIModelCatalog.SuggestedModel(id: "deepseek-r1", label: "DeepSeek R1"),
            APIModelCatalog.SuggestedModel(id: "gemma2", label: "Gemma 2"),
            APIModelCatalog.SuggestedModel(id: "command-r", label: "Command R"),
            APIModelCatalog.SuggestedModel(id: "codellama", label: "CodeLlama"),
            APIModelCatalog.SuggestedModel(id: "starcoder2", label: "StarCoder2"),
        ],
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            header
            activeCard
            simpleLibraryCard

            DisclosureGroup(isExpanded: $showAdvancedModelManagement) {
                VStack(alignment: .leading, spacing: 10) {
                    downloadCard
                    suggestedCard(suggestedForDisplay)
                    advancedProviderCatalog
                }
                .padding(.top, 8)
            } label: {
                Text("Advanced model management")
                    .font(AmaryllisTheme.bodyFont(size: 13, weight: .semibold))
                    .foregroundStyle(AmaryllisTheme.textSecondary)
            }
            .amaryllisCard()

            if let error = appState.lastError {
                Text(error)
                    .font(AmaryllisTheme.bodyFont(size: 12, weight: .medium))
                    .foregroundStyle(AmaryllisTheme.accent)
            }
        }
        .onAppear {
            if modelToDownload.isEmpty {
                modelToDownload = appState.modelCatalog?.active.model ?? "mlx-community/Qwen2.5-1.5B-Instruct-4bit"
            }
            if !providerOptions.contains(providerForDownload) {
                providerForDownload = providerOptions.first ?? "mlx"
            }
            Task { await appState.refreshModels() }
        }
        .onChange(of: providerOptions) { options in
            if !options.contains(providerForDownload) {
                providerForDownload = options.first ?? "mlx"
            }
        }
    }

    private var header: some View {
        HStack {
            Text("Models")
                .font(AmaryllisTheme.titleFont(size: 30))
                .foregroundStyle(AmaryllisTheme.textPrimary)
            Spacer()
            Button {
                Task { await appState.quickSetup() }
            } label: {
                if appState.isQuickSetupRunning {
                    ProgressView()
                        .controlSize(.small)
                        .tint(AmaryllisTheme.textPrimary)
                        .frame(width: 106)
                } else {
                    Text("Quick Setup")
                        .frame(width: 106)
                }
            }
            .buttonStyle(AmaryllisPrimaryButtonStyle())
            .disabled(appState.isQuickSetupRunning)
            Button("Refresh") {
                Task { await appState.refreshModels() }
            }
            .buttonStyle(AmaryllisSecondaryButtonStyle())
        }
    }

    private var activeCard: some View {
        HStack(spacing: 8) {
            Text("Active")
                .font(AmaryllisTheme.bodyFont(size: 12, weight: .semibold))
                .foregroundStyle(AmaryllisTheme.textSecondary)
            Text("\(appState.modelCatalog?.active.provider ?? "-") / \(appState.modelCatalog?.active.model ?? "-")")
                .font(AmaryllisTheme.monoFont(size: 12, weight: .regular))
                .foregroundStyle(AmaryllisTheme.textPrimary)
            Spacer()
            Text(appState.hasActiveModelConfigured ? "ready" : "install model")
                .font(AmaryllisTheme.bodyFont(size: 11, weight: .semibold))
                .foregroundStyle(appState.hasActiveModelConfigured ? AmaryllisTheme.okGreen : AmaryllisTheme.accent)
        }
        .amaryllisCard()
    }

    private var simpleLibraryCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Simple Library")
                .font(AmaryllisTheme.sectionFont(size: 17))
                .foregroundStyle(AmaryllisTheme.textPrimary)

            Text("Pick one model and press Install & Use. Amaryllis will download it and activate it automatically.")
                .font(AmaryllisTheme.bodyFont(size: 12, weight: .medium))
                .foregroundStyle(AmaryllisTheme.textSecondary)

            TextField("Search model", text: $quickSearch)
                .textFieldStyle(AmaryllisTerminalTextFieldStyle())

            if filteredQuickSuggestions.isEmpty {
                Text("No models found for current filter.")
                    .font(AmaryllisTheme.bodyFont(size: 12, weight: .medium))
                    .foregroundStyle(AmaryllisTheme.textSecondary)
            } else {
                ForEach(filteredQuickSuggestions.prefix(8)) { suggestion in
                    HStack(spacing: 8) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(suggestion.model.label)
                                .font(AmaryllisTheme.bodyFont(size: 12, weight: .semibold))
                                .foregroundStyle(AmaryllisTheme.textPrimary)
                            Text("\(suggestion.provider)/\(suggestion.model.id)")
                                .font(AmaryllisTheme.monoFont(size: 11, weight: .regular))
                                .foregroundStyle(AmaryllisTheme.textSecondary)
                                .lineLimit(1)
                                .truncationMode(.middle)
                        }
                        Spacer()
                        Button {
                            Task {
                                quickSearch = ""
                                await installAndActivate(modelID: suggestion.model.id, provider: suggestion.provider)
                            }
                        } label: {
                            if appState.isBusy, downloadingModelID == suggestion.model.id {
                                ProgressView().controlSize(.small).frame(width: 110)
                            } else {
                                Text("Install & Use").frame(width: 110)
                            }
                        }
                        .buttonStyle(AmaryllisPrimaryButtonStyle())
                        .disabled(appState.isBusy)
                    }
                    .padding(.vertical, 2)
                }
            }
        }
        .amaryllisCard()
    }

    private var downloadCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Install model")
                .font(AmaryllisTheme.sectionFont(size: 17))
                .foregroundStyle(AmaryllisTheme.textPrimary)

            HStack(spacing: 8) {
                TextField("Model id", text: $modelToDownload)
                    .textFieldStyle(AmaryllisTerminalTextFieldStyle())

                Picker("Provider", selection: $providerForDownload) {
                    ForEach(providerOptions, id: \.self) { provider in
                        Text(provider).tag(provider)
                    }
                }
                .pickerStyle(.menu)
                .frame(width: 120)

                Button {
                    let trimmed = modelToDownload.trimmingCharacters(in: .whitespacesAndNewlines)
                    guard !trimmed.isEmpty else { return }
                    Task { await startDownload(modelId: trimmed, provider: providerForDownload) }
                } label: {
                    if appState.isBusy, downloadingModelID == modelToDownload {
                        ProgressView().controlSize(.small).frame(width: 74)
                    } else {
                        Text("Install").frame(width: 74)
                    }
                }
                .buttonStyle(AmaryllisPrimaryButtonStyle())
                .disabled(appState.isBusy)
            }
        }
        .amaryllisCard()
    }

    private func suggestedCard(_ suggested: [String: [APIModelCatalog.SuggestedModel]]) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Suggested open models")
                .font(AmaryllisTheme.sectionFont(size: 17))
                .foregroundStyle(AmaryllisTheme.textPrimary)

            if !hasSuggestedModels {
                Text("No suggestions available yet.")
                    .font(AmaryllisTheme.bodyFont(size: 12, weight: .medium))
                    .foregroundStyle(AmaryllisTheme.textSecondary)
            } else {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 8) {
                        ForEach(suggested.keys.sorted(), id: \.self) { provider in
                            if let items = suggested[provider], !items.isEmpty {
                                VStack(alignment: .leading, spacing: 6) {
                                    Text(provider.uppercased())
                                        .font(AmaryllisTheme.bodyFont(size: 11, weight: .bold))
                                        .foregroundStyle(AmaryllisTheme.textSecondary)

                                    ForEach(items) { item in
                                        HStack(spacing: 8) {
                                            VStack(alignment: .leading, spacing: 2) {
                                                Text(item.label)
                                                    .font(AmaryllisTheme.bodyFont(size: 12, weight: .semibold))
                                                    .foregroundStyle(AmaryllisTheme.textPrimary)
                                                Text(item.id)
                                                    .font(AmaryllisTheme.monoFont(size: 11, weight: .regular))
                                                    .foregroundStyle(AmaryllisTheme.textSecondary)
                                            }
                                            Spacer()
                                            Button {
                                                Task { await startDownload(modelId: item.id, provider: provider) }
                                            } label: {
                                                if appState.isBusy, downloadingModelID == item.id {
                                                    ProgressView().controlSize(.small).frame(width: 66)
                                                } else {
                                                    Text("Install").frame(width: 66)
                                                }
                                            }
                                            .buttonStyle(AmaryllisPrimaryButtonStyle())
                                            .disabled(appState.isBusy)
                                        }
                                        .padding(.vertical, 2)
                                        .contentShape(Rectangle())
                                        .onTapGesture {
                                            providerForDownload = provider
                                            modelToDownload = item.id
                                        }
                                    }
                                }
                                .padding(.bottom, 4)
                            }
                        }
                    }
                }
                .frame(maxHeight: 280)
            }
        }
        .amaryllisCard()
    }

    private func providerSection(name: String, payload: APIModelCatalog.ProviderPayload) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(name.uppercased())
                    .font(AmaryllisTheme.bodyFont(size: 11, weight: .bold))
                    .foregroundStyle(AmaryllisTheme.textSecondary)
                Spacer()
                Text(payload.available ? "ready" : "unavailable")
                    .font(AmaryllisTheme.bodyFont(size: 11, weight: .semibold))
                    .foregroundStyle(payload.available ? .green : AmaryllisTheme.accent)
            }

            if let error = payload.error {
                Text(error)
                    .font(AmaryllisTheme.bodyFont(size: 11, weight: .medium))
                    .foregroundStyle(AmaryllisTheme.accent)
            }

            if payload.items.isEmpty {
                Text("No local models")
                    .font(AmaryllisTheme.bodyFont(size: 12, weight: .regular))
                    .foregroundStyle(AmaryllisTheme.textSecondary)
            } else {
                ForEach(payload.items) { item in
                    HStack(spacing: 8) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(item.id)
                                .font(AmaryllisTheme.bodyFont(size: 12, weight: .semibold))
                                .foregroundStyle(AmaryllisTheme.textPrimary)
                            if let path = item.path {
                                Text(path)
                                    .font(AmaryllisTheme.monoFont(size: 10, weight: .regular))
                                    .foregroundStyle(AmaryllisTheme.textSecondary)
                                    .lineLimit(1)
                                    .truncationMode(.middle)
                            }
                        }
                        Spacer()

                        if item.active || appState.modelCatalog?.active.model == item.id {
                            Text("active")
                                .font(AmaryllisTheme.bodyFont(size: 10, weight: .bold))
                                .foregroundStyle(AmaryllisTheme.accent)
                        }

                        Button {
                            loadingModelID = item.id
                            Task {
                                await appState.loadModel(modelId: item.id, provider: name)
                                loadingModelID = nil
                            }
                        } label: {
                            if loadingModelID == item.id, appState.isBusy {
                                ProgressView().controlSize(.small).frame(width: 56)
                            } else {
                                Text("Load").frame(width: 56)
                            }
                        }
                        .buttonStyle(AmaryllisSecondaryButtonStyle())
                        .disabled(appState.isBusy)
                    }
                    .padding(.vertical, 2)
                }
            }
        }
        .amaryllisCard()
    }

    private var advancedProviderCatalog: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 8) {
                if let catalog = appState.modelCatalog {
                    ForEach(catalog.providers.keys.sorted(), id: \.self) { providerName in
                        if let payload = catalog.providers[providerName] {
                            providerSection(name: providerName, payload: payload)
                        }
                    }
                } else {
                    Text("No model data yet")
                        .font(AmaryllisTheme.bodyFont(size: 12, weight: .medium))
                        .foregroundStyle(AmaryllisTheme.textSecondary)
                }
            }
        }
        .frame(maxHeight: 260)
    }

    private var suggestedForDisplay: [String: [APIModelCatalog.SuggestedModel]] {
        if let suggested = appState.modelCatalog?.suggested {
            let nonEmpty = suggested.values.contains { !$0.isEmpty }
            if nonEmpty {
                return suggested
            }
        }
        return fallbackSuggested
    }

    private var hasSuggestedModels: Bool {
        suggestedForDisplay.values.contains { !$0.isEmpty }
    }

    private var providerOptions: [String] {
        if let catalog = appState.modelCatalog {
            let keys = catalog.providers.keys.sorted()
            if !keys.isEmpty {
                return keys
            }
        }
        return ["mlx", "ollama"]
    }

    private func startDownload(modelId: String, provider: String) async {
        providerForDownload = provider
        modelToDownload = modelId
        downloadingModelID = modelId
        await appState.downloadModel(modelId: modelId, provider: provider)
        downloadingModelID = nil
    }

    private func installAndActivate(modelID: String, provider: String) async {
        providerForDownload = provider
        modelToDownload = modelID
        downloadingModelID = modelID
        await appState.installAndActivateModel(modelId: modelID, provider: provider)
        loadingModelID = modelID
        downloadingModelID = nil
        loadingModelID = nil
    }

    private var filteredQuickSuggestions: [QuickSuggestion] {
        let term = quickSearch.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        var items: [QuickSuggestion] = []
        for provider in suggestedForDisplay.keys.sorted() {
            let suggested = suggestedForDisplay[provider] ?? []
            for item in suggested {
                let candidate = "\(provider) \(item.id) \(item.label)".lowercased()
                if term.isEmpty || candidate.contains(term) {
                    items.append(
                        QuickSuggestion(
                            id: "\(provider)::\(item.id)",
                            provider: provider,
                            model: item
                        )
                    )
                }
            }
        }
        return items
    }

    private struct QuickSuggestion: Identifiable {
        let id: String
        let provider: String
        let model: APIModelCatalog.SuggestedModel
    }
}
