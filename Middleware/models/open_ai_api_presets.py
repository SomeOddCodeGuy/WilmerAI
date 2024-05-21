class OpenAiApiPresets:

    def __init__(
            self,
            temperature,
            top_p,
            typical,
            sampler_seed,
            min_p,
            repetition_penalty,
            frequency_penalty,
            presence_penalty,
            top_k,
            length_penalty,
            early_stopping,
            add_bos_token,
            dynamic_temperature,
            dynatemp_low,
            dynatemp_high,
            dynatemp_range,
            dynatemp_exponent,
            smoothing_factor,
            max_tokens_second,
            stopping_strings,
            stop,
            ban_eos_token,
            skip_special_tokens,
            top_a,
            tfs,
            mirostat_mode,
            mirostat_tau,
            mirostat_eta,
            custom_token_bans,
            sampler_order,
            rep_pen,
            rep_pen_range,
            repetition_penalty_range,
            seed,
            guidance_scale,
            negative_prompt,
            grammar_string,
            repeat_penalty,
            tfs_z,
            repeat_last_n,
            n_predict,
            mirostat,
            ignore_eos,
            truncation_length=2048,
            max_new_tokens=400,
            max_tokens=400,
            min_tokens=0
    ):
        self.max_new_tokens = max_new_tokens
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.top_p = top_p
        self.typical = typical
        self.sampler_seed = sampler_seed
        self.min_p = min_p
        self.repetition_penalty = repetition_penalty
        self.frequency_penalty = frequency_penalty
        self.presence_penalty = presence_penalty
        self.top_k = top_k
        self.min_tokens = min_tokens
        self.length_penalty = length_penalty
        self.early_stopping = early_stopping
        self.add_bos_token = add_bos_token
        self.dynamic_temperature = dynamic_temperature
        self.dynatemp_low = dynatemp_low
        self.dynatemp_high = dynatemp_high
        self.dynatemp_range = dynatemp_range
        self.dynatemp_exponent = dynatemp_exponent
        self.smoothing_factor = smoothing_factor
        self.max_tokens_second = max_tokens_second
        self.stopping_strings = stopping_strings
        self.stop = stop
        self.truncation_length = truncation_length
        self.ban_eos_token = ban_eos_token
        self.skip_special_tokens = skip_special_tokens
        self.top_a = top_a
        self.tfs = tfs
        self.mirostat_mode = mirostat_mode
        self.mirostat_tau = mirostat_tau
        self.mirostat_eta = mirostat_eta
        self.custom_token_bans = custom_token_bans
        self.sampler_order = sampler_order
        self.rep_pen = rep_pen
        self.rep_pen_range = rep_pen_range
        self.repetition_penalty_range = repetition_penalty_range
        self.seed = seed
        self.guidance_scale = guidance_scale
        self.negative_prompt = negative_prompt
        self.grammar_string = grammar_string
        self.repeat_penalty = repeat_penalty
        self.tfs_z = tfs_z
        self.repeat_last_n = repeat_last_n
        self.n_predict = n_predict
        self.mirostat = mirostat
        self.ignore_eos = ignore_eos

    def to_json(self):
        """
        Convert the attributes of the object to a JSON format.

        :return: A JSON object representing the attributes of the object.
        """
        return {
            "max_new_tokens": self.max_new_tokens,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "typical_p": self.typical,
            "sampler_seed": self.sampler_seed,
            "min_p": self.min_p,
            "repetition_penalty": self.repetition_penalty,
            "frequency_penalty": self.frequency_penalty,
            "presence_penalty": self.presence_penalty,
            "top_k": self.top_k,
            "min_tokens": self.min_tokens,
            "length_penalty": self.length_penalty,
            "early_stopping": self.early_stopping,
            "add_bos_token": self.add_bos_token,
            "dynamic_temperature": self.dynamic_temperature,
            "dynatemp_low": self.dynatemp_low,
            "dynatemp_high": self.dynatemp_high,
            "dynatemp_range": self.dynatemp_range,
            "dynatemp_exponent": self.dynatemp_exponent,
            "smoothing_factor": self.smoothing_factor,
            "max_tokens_second": self.max_tokens_second,
            "stopping_strings": self.stopping_strings,
            "stop": self.stop,
            "truncation_length": self.truncation_length,
            "ban_eos_token": self.ban_eos_token,
            "skip_special_tokens": self.skip_special_tokens,
            "top_a": self.top_a,
            "tfs": self.tfs,
            "mirostat_mode": self.mirostat_mode,
            "mirostat_tau": self.mirostat_tau,
            "mirostat_eta": self.mirostat_eta,
            "custom_token_bans": self.custom_token_bans,
            "sampler_order": self.sampler_order,
            "rep_pen": self.rep_pen,
            "rep_pen_range": self.rep_pen_range,
            "repetition_penalty_range": self.repetition_penalty_range,
            "seed": self.seed,
            "guidance_scale": self.guidance_scale,
            "negative_prompt": self.negative_prompt,
            "grammar_string": self.grammar_string,
            "repeat_penalty": self.repeat_penalty,
            "tfs_z": self.tfs_z,
            "repeat_last_n": self.repeat_last_n,
            "n_predict": self.n_predict,
            "mirostat": self.mirostat,
            "ignore_eos": self.ignore_eos
        }
