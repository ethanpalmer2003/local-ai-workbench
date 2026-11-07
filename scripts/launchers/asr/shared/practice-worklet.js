/* Keep microphone framing independent of UI/network scheduling. */
class PracticeMicrophone extends AudioWorkletProcessor {
    constructor() { super(); this.frame = new Float32Array(512); this.used = 0; }
    process(inputs) {
        const samples = inputs[0]?.[0];
        if (samples) for (const value of samples) {
            this.frame[this.used++] = value;
            if (this.used === 512) {
                this.port.postMessage(this.frame);
                this.frame = new Float32Array(512); this.used = 0;
            }
        }
        return true;
    }
}
registerProcessor('practice-microphone', PracticeMicrophone);
